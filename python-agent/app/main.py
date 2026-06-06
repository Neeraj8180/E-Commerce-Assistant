"""FastAPI entrypoint for the Python agent service."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.conversations import load_conversation
from app.db import close_pool, init_pool
from app.kafka import close_publisher, init_publisher
from app.observability import configure_logging, get_logger
from app.observability.tracing import init_tracing
from app.orchestrator import Orchestrator
from app.validation import (
    MAX_MESSAGE_CHARS,
    ValidationError,
    is_session_id,
    sanitize_text,
    validate_context,
)

log = get_logger("ecom-agent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("python_agent_starting", model=settings.ollama_model, otel=settings.otel_endpoint or "disabled")
    await init_pool()
    await init_publisher()
    init_tracing(app)
    app.state.orchestrator = Orchestrator()
    try:
        yield
    finally:
        await close_publisher()
        await close_pool()
        log.info("python_agent_stopped")


app = FastAPI(
    title="E-Commerce Agent Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(ValidationError)
async def _project_validation_handler(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "validation_failed", "detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def _pydantic_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "validation_failed", "detail": exc.errors()})


class ProcessQueryRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=254)
    session_id: str | None = Field(default=None, max_length=128)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_CHARS)
    context: dict[str, Any] | None = None
    request_id: str | None = Field(default=None, max_length=128)

    @field_validator("session_id")
    @classmethod
    def _check_session(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not is_session_id(v):
            raise ValueError("session_id must match [A-Za-z0-9_-]{1,128}")
        return v

    @field_validator("message")
    @classmethod
    def _sanitize_message(cls, v: str) -> str:
        cleaned = sanitize_text(v, max_chars=MAX_MESSAGE_CHARS)
        if not cleaned:
            raise ValueError("message is empty after sanitisation")
        return cleaned

    @field_validator("context")
    @classmethod
    def _validate_context(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        return validate_context(v)


class ProcessQueryResponse(BaseModel):
    session_id: str
    intent: str
    reply: str
    outcome: str
    escalated: bool = False
    tools_used: list[str] = []
    metadata: dict[str, Any] = {}


class ReplayRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)

    @field_validator("session_id")
    @classmethod
    def _check_session(cls, v: str) -> str:
        if not is_session_id(v):
            raise ValueError("session_id must match [A-Za-z0-9_-]{1,128}")
        return v


@app.get("/health")
async def health() -> dict[str, Any]:
    from app.db import get_pool

    db_ok = True
    db_err = ""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_err = str(exc)
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "python-agent",
        "dependencies": {"postgres": "up" if db_ok else f"down: {db_err}"},
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/process_query", response_model=ProcessQueryResponse)
async def process_query(req: ProcessQueryRequest, request: Request) -> ProcessQueryResponse:
    orchestrator: Orchestrator = request.app.state.orchestrator
    result = await orchestrator.process(
        user_id=req.user_id,
        session_id=req.session_id,
        message=req.message,
        context=req.context,
        request_id=req.request_id,
    )
    return ProcessQueryResponse(**result.to_dict())


@app.post("/replay", response_model=ProcessQueryResponse)
async def replay(req: ReplayRequest, request: Request) -> ProcessQueryResponse:
    convo = await load_conversation(req.session_id)
    if convo is None:
        raise HTTPException(status_code=404, detail=f"session {req.session_id} not found")

    user_messages = [m for m in convo["messages"] if m.get("role") == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="no user message in conversation to replay")
    last_user = user_messages[-1]["content"]

    orchestrator: Orchestrator = request.app.state.orchestrator
    result = await orchestrator.process(
        user_id=convo.get("user_id") or "replay-user",
        session_id=f"replay-{uuid.uuid4()}",
        message=last_user,
        context=(convo.get("metadata") or {}).get("context"),
        request_id=f"replay-{req.session_id}",
    )
    out = result.to_dict()
    out["metadata"]["replayed_from"] = req.session_id
    return ProcessQueryResponse(**out)
