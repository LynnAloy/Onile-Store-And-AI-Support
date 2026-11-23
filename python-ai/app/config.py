import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)
    java_base_url: str = "http://127.0.0.1:8080"
    service_key: str = Field(min_length=32, repr=False)
    ollama_base_url: str = "http://127.0.0.1:11434"
    model: str = Field(default="deepseek-r1:1.5b", min_length=1, max_length=100)
    model_api_key: str = Field(default="", repr=False)
    model_temperature: float = Field(default=0.2, ge=0, le=1)
    database_path: Path = Path(__file__).resolve().parent.parent / "data" / "conversations.db"
    model_timeout: float = Field(default=120, gt=0, le=240)
    model_read_timeout: float = Field(default=30, gt=0, le=60)
    context_char_limit: int = Field(default=6000, ge=4500, le=16000)
    context_turn_limit: int = Field(default=10, ge=1, le=30)
    output_char_limit: int = Field(default=12000, ge=1, le=32000)
    knowledge_database_path: Path = Path(__file__).resolve().parent.parent / "data" / "knowledge.db"
    embedding_model: str = "bge-m3:latest"
    embedding_timeout: float = Field(default=60, gt=0, le=120)
    rag_enabled: bool = True
    rag_min_similarity: float = Field(default=0.55, ge=0, le=1)
    rag_query_rewrite: bool = False
    rag_hyde: bool = False
    rag_llm_rerank: bool = False

    @field_validator("java_base_url", "ollama_base_url")
    @classmethod
    def service_url(cls, value):
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Service URL must be HTTP(S) without embedded credentials")
        if url.query or url.fragment:
            raise ValueError("Service URL cannot contain a query or fragment")
        return value.rstrip("/")

    @classmethod
    def from_env(cls):
        values = {
            "java_base_url": os.getenv("JAVA_BASE_URL", "http://127.0.0.1:8080"),
            "service_key": os.getenv("AI_SERVICE_KEY", ""),
            "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            "model": os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b"),
            "model_api_key": os.getenv("OLLAMA_API_KEY", ""),
            "model_temperature": os.getenv("MODEL_TEMPERATURE", "0.2"),
            "model_timeout": os.getenv("MODEL_TIMEOUT_SECONDS", "120"),
            "model_read_timeout": os.getenv("MODEL_READ_TIMEOUT_SECONDS", "30"),
            "context_char_limit": os.getenv("CONTEXT_CHAR_LIMIT", "6000"),
            "context_turn_limit": os.getenv("CONTEXT_TURN_LIMIT", "10"),
            "output_char_limit": os.getenv("MODEL_OUTPUT_CHAR_LIMIT", "12000"),
            "embedding_model": os.getenv("EMBEDDING_MODEL", "bge-m3:latest"),
            "embedding_timeout": os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60"),
            "rag_enabled": os.getenv("RAG_ENABLED", "true"),
            "rag_min_similarity": os.getenv("RAG_MIN_SIMILARITY", "0.55"),
            "rag_query_rewrite": os.getenv("RAG_QUERY_REWRITE", "false"),
            "rag_hyde": os.getenv("RAG_HYDE", "false"),
            "rag_llm_rerank": os.getenv("RAG_LLM_RERANK", "false"),
        }
        if os.getenv("AI_DATABASE_PATH"):
            values["database_path"] = Path(os.environ["AI_DATABASE_PATH"])
        if os.getenv("KNOWLEDGE_DATABASE_PATH"):
            values["knowledge_database_path"] = Path(os.environ["KNOWLEDGE_DATABASE_PATH"])
        return cls(**values)
