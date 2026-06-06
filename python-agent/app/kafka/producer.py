"""Best-effort Kafka producer.

The agent always emits events asynchronously and never blocks the user
request on Kafka availability. If Kafka is down we log and drop the event
so the service stays available.
"""

from __future__ import annotations

import json
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.config import settings
from app.observability import get_logger

log = get_logger(__name__)


class EventPublisher:
    def __init__(self, bootstrap: str) -> None:
        self.bootstrap = bootstrap
        self._producer: AIOKafkaProducer | None = None
        self._started = False

    async def start(self) -> None:
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                acks=1,
                linger_ms=20,
                request_timeout_ms=10000,
            )
            await self._producer.start()
            self._started = True
            log.info("kafka_producer_started", bootstrap=self.bootstrap)
        except (KafkaError, OSError) as exc:
            log.warning("kafka_producer_unavailable", error=str(exc))
            self._started = False

    async def stop(self) -> None:
        if self._producer and self._started:
            try:
                await self._producer.stop()
            except KafkaError:
                pass
        self._started = False

    async def publish(self, topic: str, event: dict[str, Any], key: str | None = None) -> None:
        if not self._started or self._producer is None:
            log.debug("kafka_skip_publish", topic=topic, reason="producer_not_started")
            return
        try:
            key_bytes = key.encode("utf-8") if key else None
            await self._producer.send_and_wait(topic, value=event, key=key_bytes)
        except KafkaError as exc:
            log.warning("kafka_publish_failed", topic=topic, error=str(exc))


_publisher: EventPublisher | None = None


async def init_publisher() -> EventPublisher:
    global _publisher
    if _publisher is None:
        _publisher = EventPublisher(settings.kafka_bootstrap_servers)
        await _publisher.start()
    return _publisher


async def close_publisher() -> None:
    global _publisher
    if _publisher is not None:
        await _publisher.stop()
        _publisher = None


def get_publisher() -> EventPublisher:
    if _publisher is None:
        raise RuntimeError("Kafka publisher not initialised")
    return _publisher
