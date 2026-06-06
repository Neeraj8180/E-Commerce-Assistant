"""Return / Exchange Planner agent.

Mixes deterministic business rules (eligibility, refund tiers) with RAG-grounded
policy context for the user-facing rationale. Side effects (Shopify return,
Stripe refund) are executed via the tools layer when the plan is approved.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import settings
from app.observability import AGENT_FAILURE, AGENT_LATENCY, AGENT_SUCCESS, ESCALATION_TOTAL, get_logger
from app.tools import orders as orders_tool
from app.tools import policy_rag, shopify_mock, stripe_mock

log = get_logger(__name__)

PlanOutcome = Literal[
    "approved_auto",
    "approved_manager_review",
    "rejected_window",
    "rejected_status",
    "rejected_not_found",
    "exchange_created",
    "exchange_out_of_stock",
    "error",
]


@dataclass
class ReturnPlan:
    order_id: str
    eligible: bool
    outcome: PlanOutcome
    reason: str
    refund_amount: float = 0.0
    workflow: list[str] = field(default_factory=list)
    rma_id: str | None = None
    refund_id: str | None = None
    exchange_id: str | None = None
    policy_chunks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "eligible": self.eligible,
            "outcome": self.outcome,
            "reason": self.reason,
            "refund_amount": self.refund_amount,
            "workflow": self.workflow,
            "rma_id": self.rma_id,
            "refund_id": self.refund_id,
            "exchange_id": self.exchange_id,
            "policies_cited": [c["doc_id"] for c in self.policy_chunks],
        }


class ReturnPlannerAgent:
    name = "return_planner"

    async def plan_return(
        self,
        *,
        order_id: str,
        reason: str,
        item_skus: list[str] | None = None,
    ) -> ReturnPlan:
        start = time.perf_counter()
        try:
            plan = await self._plan_return_inner(order_id, reason, item_skus or [])
            AGENT_SUCCESS.labels(agent_name=self.name, intent="return").inc()
            return plan
        except Exception as exc:  # noqa: BLE001
            AGENT_FAILURE.labels(agent_name=self.name, reason="exception").inc()
            log.error("planner_failed", error=str(exc), order_id=order_id)
            raise
        finally:
            AGENT_LATENCY.labels(agent_name=self.name, intent="return").observe(time.perf_counter() - start)

    async def _plan_return_inner(self, order_id: str, reason: str, item_skus: list[str]) -> ReturnPlan:
        order = await orders_tool.get_order(order_id)
        chunks = await policy_rag.search_policies(f"return policy {reason}", top_k=settings.rag_top_k)
        cited = policy_rag.chunks_to_metadata(chunks)

        if order is None:
            return ReturnPlan(
                order_id=order_id,
                eligible=False,
                outcome="rejected_not_found",
                reason=f"No order found with id {order_id}.",
                policy_chunks=cited,
            )

        eligible, eligibility_reason = orders_tool.is_within_return_window(order)
        if not eligible:
            outcome: PlanOutcome = "rejected_status" if order["status"] != "delivered" else "rejected_window"
            return ReturnPlan(
                order_id=order_id,
                eligible=False,
                outcome=outcome,
                reason=eligibility_reason,
                policy_chunks=cited,
            )

        refund_amount = self._compute_refund(order, item_skus)
        requires_manager = refund_amount >= settings.refund_auto_approve_limit

        workflow = ["validate_order", "check_policies", "create_return"]
        if requires_manager:
            workflow.append("manager_review")
        workflow.append("process_refund")
        workflow.append("notify_customer")

        plan = ReturnPlan(
            order_id=order_id,
            eligible=True,
            outcome="approved_manager_review" if requires_manager else "approved_auto",
            reason=(
                f"Eligible. {eligibility_reason} Refund ${refund_amount:.2f} "
                + ("requires manager review." if requires_manager else "auto-approved.")
            ),
            refund_amount=refund_amount,
            workflow=workflow,
            policy_chunks=cited,
        )

        if requires_manager:
            ESCALATION_TOTAL.labels(reason="refund_over_limit").inc()
            return plan

        skus_to_return = item_skus or [item["sku"] for item in order["items"]]

        shopify_resp = await shopify_mock.create_return(
            order_id=order_id, item_skus=skus_to_return, reason=reason
        )
        plan.rma_id = shopify_resp.get("rma_id")

        stripe_resp = await stripe_mock.process_refund(
            order_id=order_id, amount=refund_amount, idempotency_key=str(uuid.uuid4())
        )
        plan.refund_id = stripe_resp.get("refund_id")

        return plan

    async def plan_exchange(
        self,
        *,
        order_id: str,
        original_sku: str,
        new_sku: str,
        reason: str,
    ) -> ReturnPlan:
        start = time.perf_counter()
        try:
            order = await orders_tool.get_order(order_id)
            chunks = await policy_rag.search_policies(f"exchange policy {reason}", top_k=settings.rag_top_k)
            cited = policy_rag.chunks_to_metadata(chunks)

            if order is None:
                return ReturnPlan(
                    order_id=order_id,
                    eligible=False,
                    outcome="rejected_not_found",
                    reason=f"No order found with id {order_id}.",
                    policy_chunks=cited,
                )

            eligible, eligibility_reason = orders_tool.is_within_return_window(order)
            if not eligible:
                outcome: PlanOutcome = "rejected_status" if order["status"] != "delivered" else "rejected_window"
                return ReturnPlan(
                    order_id=order_id,
                    eligible=False,
                    outcome=outcome,
                    reason=eligibility_reason,
                    policy_chunks=cited,
                )

            resp = await shopify_mock.create_exchange(
                order_id=order_id, original_sku=original_sku, new_sku=new_sku, reason=reason
            )

            if resp.get("status") == "out_of_stock":
                return ReturnPlan(
                    order_id=order_id,
                    eligible=True,
                    outcome="exchange_out_of_stock",
                    reason=f"Requested replacement {new_sku} is out of stock. Offer refund or store credit.",
                    workflow=["validate_order", "check_stock", "offer_refund_or_credit"],
                    policy_chunks=cited,
                )

            plan = ReturnPlan(
                order_id=order_id,
                eligible=True,
                outcome="exchange_created",
                reason=f"Exchange created: {original_sku} -> {new_sku}.",
                workflow=["validate_order", "check_policies", "create_exchange", "ship_replacement"],
                exchange_id=resp.get("exchange_id"),
                policy_chunks=cited,
            )
            AGENT_SUCCESS.labels(agent_name=self.name, intent="exchange").inc()
            return plan
        except Exception as exc:  # noqa: BLE001
            AGENT_FAILURE.labels(agent_name=self.name, reason="exception").inc()
            log.error("exchange_failed", error=str(exc), order_id=order_id)
            raise
        finally:
            AGENT_LATENCY.labels(agent_name=self.name, intent="exchange").observe(time.perf_counter() - start)

    @staticmethod
    def _compute_refund(order: dict[str, Any], item_skus: list[str]) -> float:
        items = order["items"]
        if not item_skus:
            return float(order["total_amount"])
        total = 0.0
        for item in items:
            if item["sku"] in item_skus:
                total += float(item["unit_price"]) * int(item["quantity"])
        return round(total, 2)
