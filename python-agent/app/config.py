"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.2", alias="OLLAMA_MODEL")
    ollama_embed_model: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBED_MODEL")
    ollama_timeout_seconds: int = Field(default=60, alias="OLLAMA_TIMEOUT_SECONDS")
    embed_dimension: int = Field(default=768, alias="EMBED_DIMENSION")

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    groq_timeout_seconds: int = Field(default=60, alias="GROQ_TIMEOUT_SECONDS")

    # DB
    database_url: str = Field(
        default="postgresql://ecom:ecom_pass@localhost:5432/ecom_agent",
        alias="DATABASE_URL",
    )

    # Mocks
    shopify_mock_url: str = Field(default="http://localhost:8001", alias="SHOPIFY_MOCK_URL")
    stripe_mock_url: str = Field(default="http://localhost:8002", alias="STRIPE_MOCK_URL")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_conversations: str = Field(default="agent.conversations", alias="KAFKA_TOPIC_CONVERSATIONS")
    kafka_topic_tool_calls: str = Field(default="agent.tool_calls", alias="KAFKA_TOPIC_TOOL_CALLS")
    kafka_topic_escalations: str = Field(default="agent.escalations", alias="KAFKA_TOPIC_ESCALATIONS")

    # Agent behavior
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    rag_score_threshold: float = Field(default=0.5, alias="RAG_SCORE_THRESHOLD")
    memory_session_top_k: int = Field(default=3, alias="MEMORY_SESSION_TOP_K")
    memory_user_top_k: int = Field(default=3, alias="MEMORY_USER_TOP_K")
    memory_score_threshold: float = Field(default=0.40, alias="MEMORY_SCORE_THRESHOLD")
    refund_auto_approve_limit: float = Field(default=50.0, alias="REFUND_AUTO_APPROVE_LIMIT")
    return_window_days: int = Field(default=30, alias="RETURN_WINDOW_DAYS")
    max_failures_before_escalation: int = Field(default=3, alias="MAX_FAILURES_BEFORE_ESCALATION")

    # Observability
    otel_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field(default="python-agent", alias="OTEL_SERVICE_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    service_port: int = Field(default=8000, alias="PYTHON_AGENT_PORT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
