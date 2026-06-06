"""OpenTelemetry tracing setup."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

log = logging.getLogger(__name__)


def init_tracing(app) -> None:
    """Initialise tracing for the FastAPI app and httpx clients.

    If OTEL_EXPORTER_OTLP_ENDPOINT is empty this becomes a no-op so the
    service still runs cleanly in environments without an OTel collector.
    """

    if not settings.otel_endpoint:
        log.info("otel endpoint not configured; tracing disabled")
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    try:
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        log.info("tracing initialised, exporting to %s", settings.otel_endpoint)
    except Exception as exc:  # noqa: BLE001 - never crash the app for tracing
        log.warning("tracing init failed: %s", exc)


def tracer():
    return trace.get_tracer("ecom-agent")
