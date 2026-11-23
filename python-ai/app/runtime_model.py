"""Reload only chat model settings from the administrator's atomically replaced local file."""
import json
import os
from pathlib import Path
from .model import OllamaModel
from .errors import AppError
from .openai_model import OpenAIModel


class RuntimeModel:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings

    async def stream(self, messages, *, context_data=None, tools=None, system_prompt=None, response_schema=None):
        settings = self.settings
        protocol = "ollama"
        path = os.getenv("AI_CONFIG_PATH")
        if path and Path(path).exists():
            try:
                value = json.loads(Path(path).read_text(encoding="utf-8"))
                protocol = value.get("protocol", "ollama")
                if protocol not in ("ollama", "openai"):
                    raise ValueError("Unsupported protocol")
                settings = type(settings).model_validate({**settings.model_dump(),
                    "model": value["model"], "ollama_base_url": value["endpoint"],
                    # Never forward an environment credential to a newly configured destination.
                    "model_api_key": value.get("apiKey", "")})
            except (ValueError, KeyError, OSError):
                raise AppError(503, "MODEL_CONFIG_INVALID", "管理员模型配置无法读取，请检查配置") from None
        adapter = OpenAIModel if protocol == "openai" else OllamaModel
        options = {"system_prompt": system_prompt} if system_prompt else {}
        if response_schema is not None:
            options["response_schema"] = response_schema
        async for item in adapter(self.client, settings).stream(messages, context_data=context_data, tools=tools, **options):
            yield item
