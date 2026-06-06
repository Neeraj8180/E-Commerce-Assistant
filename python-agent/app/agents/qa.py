"""Q&A Agent: produces the user-facing reply, grounded in tool/RAG output.

This agent never invents order or refund details. It receives a `context`
dictionary populated by the orchestrator (containing order data, plan results,
RAG chunks) and is restricted to writing prose around those facts.
"""

from __future__ import annotations

import time
from typing import Any

from app.llm import get_llm_provider
from app.observability import AGENT_LATENCY, AGENT_SUCCESS, LLM_TOKENS, get_logger
from app.memory import MemoryChunk, format_memory_for_prompt
from app.tools.policy_rag import RetrievedChunk, format_chunks_for_prompt
from app.validation import MAX_REPLY_CHARS, sanitize_text

log = get_logger(__name__)


_SYSTEM_PROMPT = (
    "You are a customer-support assistant for an e-commerce store. "
    "Be concise, friendly, and professional. "
    "Only state facts that are present in the provided context. "
    "Never invent order ids, refund amounts, dates, RMA ids, or policy details. "
    "If the context says an action was completed, confirm it and reference the relevant ids. "
    "If the context indicates a problem (ineligible, out of stock, manager review), explain it "
    "and suggest next steps. Keep the reply under 4 short sentences."
)


class QAAgent:
    name = "qa"

    async def respond(
        self,
        *,
        intent: str,
        user_message: str,
        context: dict[str, Any],
        policy_chunks: list[RetrievedChunk] | None = None,
        memory_chunks: list[MemoryChunk] | None = None,
    ) -> str:
        start = time.perf_counter()
        try:
            prompt = self._build_prompt(
                intent, user_message, context, policy_chunks or [], memory_chunks or []
            )
            llm = get_llm_provider()
            resp = await llm.complete(prompt, system=_SYSTEM_PROMPT, temperature=0.3, max_tokens=300)
            LLM_TOKENS.labels(model=resp.model, kind="prompt").inc(resp.prompt_tokens)
            LLM_TOKENS.labels(model=resp.model, kind="completion").inc(resp.completion_tokens)
            cleaned = sanitize_text(resp.text or "", max_chars=MAX_REPLY_CHARS)
            if not cleaned:
                cleaned = _fallback_reply(intent)
            AGENT_SUCCESS.labels(agent_name=self.name, intent=intent).inc()
            return cleaned
        finally:
            AGENT_LATENCY.labels(agent_name=self.name, intent=intent).observe(time.perf_counter() - start)

    @staticmethod
    def _build_prompt(
        intent: str,
        user_message: str,
        context: dict[str, Any],
        policy_chunks: list[RetrievedChunk],
        memory_chunks: list[MemoryChunk],
    ) -> str:
        ctx_lines = ["CONTEXT (use only these facts):"]
        for k, v in context.items():
            ctx_lines.append(f"- {k}: {v}")
        ctx_lines.append("")
        ctx_lines.append("CONVERSATION MEMORY (prior turns — use for continuity, not as policy facts):")
        ctx_lines.append(format_memory_for_prompt(memory_chunks))
        ctx_lines.append("")
        ctx_lines.append("RELEVANT POLICIES / FAQ:")
        ctx_lines.append(format_chunks_for_prompt(policy_chunks))
        ctx_lines.append("")
        ctx_lines.append(f"INTENT: {intent}")
        ctx_lines.append(f"USER MESSAGE: {user_message!r}")
        ctx_lines.append("")
        ctx_lines.append("Write the reply to the customer now.")
        return "\n".join(ctx_lines)


def _fallback_reply(intent: str) -> str:
    return {
        "return": "I'm sorry — I couldn't generate a reply just now. A human agent will follow up shortly.",
        "exchange": "I'm sorry — I couldn't process the exchange details. Please try again or ask for a human agent.",
        "order_status": "I'm sorry — I couldn't look up your order right now. Please try again in a moment.",
        "general_query": "I'm sorry — I don't have enough information to answer that. A human agent can help.",
        "escalate_to_human": "Connecting you with a human agent now. Please hold on.",
    }.get(intent, "I'm sorry, I couldn't complete that request.")
