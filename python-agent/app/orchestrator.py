"""Top-level agent orchestration: routes a single user turn through the
right agents and tools, persists the conversation, emits a Kafka event,
and returns a normalised response to the API gateway.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.qa import QAAgent
from app.agents.return_planner import ReturnPlannerAgent
from app.agents.router import RouterAgent
from app.config import settings
from app.conversations import append_message, load_conversation, upsert_conversation
from app.guardrails import (
    check_grounding,
    extract_order_id,
    fallback_reply,
    should_escalate,
)
from app.kafka import get_publisher
from app.observability import AGENT_FAILURE, get_logger
from app.tools import orders as orders_tool
from app.tools import policy_rag
from app.validation import (
    MAX_MESSAGE_CHARS,
    ValidationError,
    is_session_id,
    sanitize_text,
    validate_context,
)

log = get_logger(__name__)


@dataclass
class TurnResult:
    session_id: str
    intent: str
    reply: str
    outcome: str
    escalated: bool = False
    tools_used: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "intent": self.intent,
            "reply": self.reply,
            "outcome": self.outcome,
            "escalated": self.escalated,
            "tools_used": self.tools_used,
            "metadata": self.metadata,
        }


class Orchestrator:
    def __init__(self) -> None:
        self.router = RouterAgent()
        self.planner = ReturnPlannerAgent()
        self.qa = QAAgent()

    async def process(
        self,
        *,
        user_id: str,
        session_id: str | None,
        message: str,
        context: dict[str, Any] | None,
        request_id: str | None = None,
    ) -> TurnResult:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValidationError("user_id is required")
        user_id = user_id.strip()[:254]

        if session_id and not is_session_id(session_id):
            raise ValidationError("invalid session_id format")
        session_id = session_id or str(uuid.uuid4())

        message = sanitize_text(message or "", max_chars=MAX_MESSAGE_CHARS)
        if not message:
            raise ValidationError("message is empty after sanitisation")

        context = validate_context(context)
        request_id = (request_id or str(uuid.uuid4()))[:128]

        log_ctx = dict(session_id=session_id, user_id=user_id, request_id=request_id)
        log.info("turn_start", message=message[:200], **log_ctx)

        conversation = await load_conversation(session_id)
        messages = conversation["messages"] if conversation else []
        prior_meta = conversation["metadata"] if conversation else {}
        consecutive_failures = int(prior_meta.get("consecutive_failures", 0))

        append_message(messages, "user", message)

        try:
            router_result = await self.router.classify(message)
            intent = router_result.intent
        except Exception as exc:  # noqa: BLE001
            AGENT_FAILURE.labels(agent_name="router", reason="exception").inc()
            log.error("router_failed", error=str(exc), **log_ctx)
            return await self._return_fallback(
                session_id=session_id, user_id=user_id, intent="general_query",
                message=message, messages=messages, prior_meta=prior_meta,
                escalated=True, escalation_reason="router_error", reply=None,
            )

        escalated, esc_reason = should_escalate(
            confidence=router_result.confidence,
            consecutive_failures=consecutive_failures,
            user_message=message,
        )
        if escalated and intent != "escalate_to_human":
            intent = "escalate_to_human"

        tools_used: list[str] = []
        outcome = "ok"
        metadata: dict[str, Any] = {
            "router": {
                "intent": router_result.intent,
                "confidence": router_result.confidence,
                "source": router_result.source,
            },
            "request_id": request_id,
        }
        known_order_ids: list[str] = []
        known_refund_amounts: list[float] = []
        qa_context: dict[str, Any] = {}
        rag_chunks: list[policy_rag.RetrievedChunk] = []
        reply: str | None = None

        try:
            if intent == "order_status":
                order_id = extract_order_id(message, context)
                if order_id:
                    tools_used.append("get_order")
                    order = await orders_tool.get_order(order_id)
                    if order:
                        known_order_ids.append(order["id"])
                        summary = orders_tool.order_status_summary(order)
                        qa_context = {
                            "order_id": order["id"],
                            "order_summary": summary,
                            "tracking_number": order.get("tracking_number"),
                            "carrier": order.get("carrier"),
                            "estimated_delivery": order.get("estimated_delivery"),
                            "delivered_at": order.get("delivered_at"),
                        }
                        outcome = summary["headline"]
                    else:
                        outcome = "order_not_found"
                        qa_context = {"order_id": order_id, "found": False}
                else:
                    outcome = "missing_order_id"
                    qa_context = {"note": "User did not provide an order id."}
                tools_used.append("search_policies")
                rag_chunks = await policy_rag.search_policies("order tracking delivery status")

            elif intent == "return":
                order_id = extract_order_id(message, context)
                if not order_id:
                    outcome = "missing_order_id"
                    qa_context = {"note": "User did not provide an order id."}
                    tools_used.append("search_policies")
                    rag_chunks = await policy_rag.search_policies("return policy")
                else:
                    tools_used.extend(["get_order", "search_policies"])
                    plan = await self.planner.plan_return(
                        order_id=order_id,
                        reason=context.get("reason", "customer request"),
                        item_skus=context.get("item_skus"),
                    )
                    if plan.rma_id:
                        tools_used.append("shopify_create_return")
                    if plan.refund_id:
                        tools_used.append("stripe_process_refund")
                    known_order_ids.append(order_id)
                    if plan.refund_amount:
                        known_refund_amounts.append(plan.refund_amount)
                    qa_context = {"plan": plan.to_dict()}
                    outcome = plan.outcome
                    metadata["plan"] = plan.to_dict()
                    rag_chunks = await policy_rag.search_policies("return policy refund eligibility")

                    # Re-check escalation for high-value refunds we discovered now.
                    esc2, reason2 = should_escalate(
                        confidence=router_result.confidence,
                        consecutive_failures=consecutive_failures,
                        user_message=message,
                        refund_amount=plan.refund_amount,
                    )
                    if esc2:
                        escalated, esc_reason = True, reason2

            elif intent == "exchange":
                order_id = extract_order_id(message, context)
                original_sku = (str(context.get("original_sku", "")).strip().upper() or None)
                new_sku = (str(context.get("new_sku", "")).strip().upper() or None)
                if not order_id or not original_sku or not new_sku:
                    outcome = "missing_exchange_details"
                    qa_context = {
                        "note": "Need order id, original sku, and desired new sku to process an exchange.",
                        "order_id": order_id,
                        "original_sku": original_sku,
                        "new_sku": new_sku,
                    }
                    tools_used.append("search_policies")
                    rag_chunks = await policy_rag.search_policies("exchange policy")
                else:
                    tools_used.extend(["get_order", "search_policies", "shopify_create_exchange"])
                    plan = await self.planner.plan_exchange(
                        order_id=order_id,
                        original_sku=original_sku,
                        new_sku=new_sku,
                        reason=context.get("reason", "customer request"),
                    )
                    known_order_ids.append(order_id)
                    qa_context = {"plan": plan.to_dict()}
                    outcome = plan.outcome
                    metadata["plan"] = plan.to_dict()
                    rag_chunks = await policy_rag.search_policies("exchange policy out of stock")

            elif intent == "escalate_to_human":
                outcome = "escalated"
                escalated = True
                qa_context = {"note": "Connecting user with a human agent.", "reason": esc_reason or "user_request"}
                tools_used.append("search_policies")
                rag_chunks = await policy_rag.search_policies("human escalation support")

            else:  # general_query
                tools_used.append("search_policies")
                rag_chunks = await policy_rag.search_policies(message)
                qa_context = {"note": "General policy or product question."}
                outcome = "answered" if rag_chunks else "no_information"

            reply = await self.qa.respond(
                intent=intent,
                user_message=message,
                context=qa_context,
                policy_chunks=rag_chunks,
            )

            # Hallucination check
            grounding = check_grounding(
                intent=intent,
                reply=reply,
                known_order_ids=known_order_ids,
                known_refund_amounts=known_refund_amounts,
                rag_chunks=rag_chunks,
            )
            if not grounding.grounded:
                metadata["grounding"] = {
                    "fabricated_order_ids": grounding.fabricated_order_ids,
                    "unexpected_refund_amounts": grounding.unexpected_refund_amounts,
                }
                reply = fallback_reply(intent, escalated)
                outcome = "fallback_ungrounded"

        except Exception as exc:  # noqa: BLE001
            log.exception("orchestrator_failed", error=str(exc), intent=intent, **log_ctx)
            AGENT_FAILURE.labels(agent_name="orchestrator", reason=type(exc).__name__).inc()
            consecutive_failures += 1
            metadata["consecutive_failures"] = consecutive_failures
            return await self._return_fallback(
                session_id=session_id, user_id=user_id, intent=intent,
                message=message, messages=messages, prior_meta=metadata,
                escalated=True, escalation_reason="exception", reply=None,
            )

        # Reset failure counter on success.
        metadata["consecutive_failures"] = 0
        metadata["rag"] = {
            "chunks": policy_rag.chunks_to_metadata(rag_chunks),
            "count": len(rag_chunks),
        }
        if escalated:
            metadata["escalation_reason"] = esc_reason

        append_message(messages, "assistant", reply or "", meta={"intent": intent, "outcome": outcome})

        await upsert_conversation(
            session_id=session_id,
            user_id=user_id,
            intent=intent,
            outcome=outcome,
            messages=messages,
            metadata=metadata,
            escalated=escalated,
        )

        await self._publish(session_id=session_id, user_id=user_id, intent=intent, outcome=outcome,
                            escalated=escalated, tools_used=tools_used, metadata=metadata)

        return TurnResult(
            session_id=session_id,
            intent=intent,
            reply=reply or fallback_reply(intent, escalated),
            outcome=outcome,
            escalated=escalated,
            tools_used=tools_used,
            metadata=metadata,
        )

    async def _return_fallback(
        self,
        *,
        session_id: str,
        user_id: str,
        intent: str,
        message: str,
        messages: list[dict[str, Any]],
        prior_meta: dict[str, Any],
        escalated: bool,
        escalation_reason: str,
        reply: str | None,
    ) -> TurnResult:
        text = reply or fallback_reply(intent, escalated)
        outcome = "fallback"
        append_message(messages, "assistant", text, meta={"intent": intent, "outcome": outcome})
        meta = {**prior_meta, "escalation_reason": escalation_reason}
        await upsert_conversation(
            session_id=session_id,
            user_id=user_id,
            intent=intent,
            outcome=outcome,
            messages=messages,
            metadata=meta,
            escalated=escalated,
        )
        await self._publish(session_id=session_id, user_id=user_id, intent=intent, outcome=outcome,
                            escalated=escalated, tools_used=[], metadata=meta)
        return TurnResult(
            session_id=session_id, intent=intent, reply=text, outcome=outcome,
            escalated=escalated, tools_used=[], metadata=meta,
        )

    @staticmethod
    async def _publish(*, session_id: str, user_id: str, intent: str, outcome: str,
                       escalated: bool, tools_used: list[str], metadata: dict[str, Any]) -> None:
        try:
            publisher = get_publisher()
        except RuntimeError:
            return
        await publisher.publish(
            settings.kafka_topic_conversations,
            {
                "session_id": session_id,
                "user_id": user_id,
                "intent": intent,
                "outcome": outcome,
                "escalated": escalated,
                "tools_used": tools_used,
                "metadata": metadata,
            },
            key=session_id,
        )
        if escalated:
            await publisher.publish(
                settings.kafka_topic_escalations,
                {"session_id": session_id, "user_id": user_id, "intent": intent,
                 "reason": metadata.get("escalation_reason", "unknown")},
                key=session_id,
            )
