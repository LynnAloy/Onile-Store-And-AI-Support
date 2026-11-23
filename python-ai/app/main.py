import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import UUID
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from .config import Settings
from .errors import AppError
from .identity import JavaIdentity
from .model import OllamaModel
from .store import ConversationStore
from .context import prepare_context
from .knowledge import KnowledgeStore, OllamaEmbeddings
from .retrieval import HybridRetriever, validate_citations
from .tools import ReadTools
from .agent import run_agent
from .tools import DraftIntent
from .order_preparation import OrderPreparation


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="新对话", min_length=1, max_length=80)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requestId: UUID
    message: str = Field(min_length=1, max_length=4000)
    purchaseIntent: DraftIntent | None = None


class ConversationView(BaseModel):
    id: UUID
    title: str
    createdAt: int
    updatedAt: int


class TurnView(BaseModel):
    requestId: UUID
    message: str
    assistant: str
    status: Literal["processing", "completed", "failed", "interrupted"]
    errorCode: str | None
    createdAt: int
    personalizationApplied: bool = False
    profileRevision: int = 0
    citations: list[dict] = Field(default_factory=list)
    retrieval: dict = Field(default_factory=dict)
    toolEvents: list[dict] = Field(default_factory=list)


class HistoryView(BaseModel):
    id: UUID
    title: str
    turns: list[TurnView]


class ErrorView(BaseModel):
    code: str
    message: str


def event(kind, data):
    return "event: " + kind + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"


async def stream_turn(app, conversation, request_id, message, user, token, prepared, disconnected,
                      order_capability=None):
    store = app.state.store
    settings = app.state.settings
    content, state, error_code = "", "interrupted", "CLIENT_DISCONNECTED"
    pending, iterator = None, None
    binding = prepared.get("binding", {"enabled": False, "revision": 0})
    knowledge_revision = prepared.get("knowledgeRevision", 0)

    async def check_binding():
        if order_capability is not None:
            await app.state.order_preparation.check(order_capability)
        status = await app.state.identity.personalization(token)
        if status != binding:
            raise AppError(409, "PERSONALIZATION_CHANGED", "健康资料或授权已改变，本次生成已停止")
        revision = app.state.knowledge.metadata()["revision"] if settings.rag_enabled else 0
        if revision != knowledge_revision:
            raise AppError(409, "KNOWLEDGE_CHANGED", "知识库已更新，本次生成已停止")

    try:
        yield event("start", {"conversationId": conversation, "requestId": request_id,
                              "replayed": prepared["replay"]})
        if prepared["replay"]:
            await check_binding()
            yield event("context", prepared["metadata"])
            for item in prepared.get("toolEvents", []):
                yield event(item["kind"], item["data"])
            yield event("delta", {"text": prepared["assistant"]})
            yield event("done", {"requestId": request_id, "status": "completed", "replayed": True})
            return
        pending = asyncio.create_task(prepare_context(
            app, conversation, message, user, token, binding, knowledge_revision,
        ))
        stage = "prepare"
        checked_at = time.monotonic()
        metadata = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.model_timeout
        async with asyncio.timeout(settings.model_timeout):
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError()
                done, _ = await asyncio.wait({pending}, timeout=min(1, remaining))
                if loop.time() >= deadline:
                    raise TimeoutError()
                if await disconnected():
                    return
                if time.monotonic() - checked_at >= 1:
                    await check_binding()
                    checked_at = time.monotonic()
                if not done:
                    yield ": ping\n\n"
                    continue
                try:
                    value = pending.result()
                except StopAsyncIteration:
                    break
                pending = None
                if stage == "prepare":
                    await check_binding()
                    metadata = value["metadata"]
                    await asyncio.to_thread(store.attach_metadata, conversation, request_id, metadata)
                    yield event("context", metadata)
                    if order_capability is not None:
                        value["contextData"]["authorizedOrderItems"] = order_capability.items
                        value["contextData"]["orderPreparationAvailable"] = True
                    iterator = run_agent(
                        app, value["messages"], value["contextData"], token, check_binding, order_capability,
                    ).__aiter__()
                    pending = asyncio.create_task(anext(iterator))
                    stage = "generate"
                    continue
                if isinstance(value, dict):
                    await asyncio.to_thread(store.append_tool_event, conversation, request_id, value)
                    yield event(value["kind"], value["data"])
                    pending = asyncio.create_task(anext(iterator))
                    continue
                if len(content) + len(value) > settings.output_char_limit:
                    raise AppError(502, "MODEL_OUTPUT_LIMIT", "回答过长，请缩小问题范围")
                content += value
                yield event("delta", {"text": value})
                pending = asyncio.create_task(anext(iterator))
        if not content.strip():
            raise AppError(502, "MODEL_EMPTY_RESPONSE", "模型没有返回有效回答")
        await check_binding()
        validate_citations(content, metadata.get("citations", []))
        await asyncio.to_thread(store.finish, conversation, request_id, content, "completed")
        state = "completed"
        yield event("done", {"requestId": request_id, "status": "completed", "replayed": False})
    except TimeoutError:
        state, error_code = "failed", "MODEL_TIMEOUT"
        yield event("error", {"code": error_code, "message": "模型响应超时，请稍后重试"})
    except AppError as exc:
        state, error_code = "failed", exc.code
        yield event("error", exc.body())
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logging.getLogger(__name__).error("AI stream failure: %s", type(exc).__name__)
        state, error_code = "failed", "INTERNAL_ERROR"
        yield event("error", {"code": error_code, "message": "AI服务暂时不可用"})
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending
        if iterator is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await iterator.aclose()
        if not prepared["replay"] and state != "completed":
            store.finish(conversation, request_id, content, state, error_code)


class BodyLimitMiddleware:
    """Bound JSON requests while retaining receive() for streaming disconnect detection."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            part = await receive()
            if part["type"] == "http.disconnect":
                return
            data = part.get("body", b"")
            size += len(data)
            if size > 32768:
                response = JSONResponse(
                    {"code": "PAYLOAD_TOO_LARGE", "message": "请求内容过长"}, status_code=413,
                )
                return await response(scope, receive, send)
            chunks.append(data)
            if not part.get("more_body", False):
                break
        supplied = False

        async def replay():
            nonlocal supplied
            if not supplied:
                supplied = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings=None, *, java_transport=None, model_transport=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        async with httpx.AsyncClient(
            transport=java_transport, trust_env=False, follow_redirects=False, limits=limits,
        ) as java_client, httpx.AsyncClient(
            transport=model_transport, trust_env=False, follow_redirects=False, limits=limits,
        ) as model_client:
            app.state.settings = settings
            app.state.store = ConversationStore(settings.database_path)
            app.state.identity = JavaIdentity(java_client, settings)
            from .runtime_model import RuntimeModel
            app.state.model = RuntimeModel(model_client, settings)
            app.state.tools = ReadTools(java_client, settings)
            app.state.order_preparation = OrderPreparation(java_client, settings)
            app.state.knowledge = KnowledgeStore(settings.knowledge_database_path)
            app.state.embeddings = OllamaEmbeddings(model_client, settings)
            app.state.retriever = HybridRetriever(
                app.state.knowledge, app.state.embeddings, model_client, settings,
            )
            yield

    app = FastAPI(title="DeepseekDoc AI Service", version="4.2.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    bearer = HTTPBearer(auto_error=False)

    async def current(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise AppError(401, "UNAUTHORIZED", "请先登录并授权AI会话")
        user = await app.state.identity.resolve(credentials.credentials)
        return user, credentials.credentials

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"code": "VALIDATION_ERROR", "message": "请求参数不合法"}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"code": "HTTP_ERROR", "message": "接口不存在或请求方式不支持"},
                            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger(__name__).error("AI request failure: %s", type(exc).__name__)
        return JSONResponse({"code": "INTERNAL_ERROR", "message": "AI服务暂时不可用"}, status_code=500)

    @app.get("/ai/health")
    async def health():
        return {"status": "up"}

    @app.post("/ai/v1/conversations", status_code=201, response_model=ConversationView)
    async def create(body: CreateConversation, identity=Depends(current)):
        user, _ = identity
        return await asyncio.to_thread(app.state.store.create, user, body.title)

    @app.get("/ai/v1/conversations", response_model=list[ConversationView])
    async def conversations(identity=Depends(current)):
        user, _ = identity
        return await asyncio.to_thread(app.state.store.list, user)

    @app.get("/ai/v1/conversations/{conversation_id}/messages", response_model=HistoryView)
    async def history(conversation_id: UUID, identity=Depends(current)):
        user, _ = identity
        return await asyncio.to_thread(app.state.store.history, user, str(conversation_id))

    @app.post("/ai/v1/conversations/{conversation_id}/messages", response_class=StreamingResponse,
              responses={200: {"content": {"text/event-stream": {}}, "description": "start/delta/done/error SSE"}})
    async def message(conversation_id: UUID, body: MessageRequest, request: Request,
                      order_token: str | None = Header(default=None, alias="X-Order-Agent-Token"),
                      identity=Depends(current)):
        user, token = identity
        conversation = str(conversation_id)
        request_id = str(body.requestId)
        order_capability = None
        if (body.purchaseIntent is None) != (order_token is None):
            raise AppError(400, "ORDER_AUTHORIZATION_REQUIRED", "订单准备需同时提供指定商品意图与独立授权")
        if body.purchaseIntent is not None:
            order_capability = await app.state.order_preparation.capability(
                order_token, user, body.purchaseIntent.model_dump()["items"],
            )
        binding = await app.state.identity.personalization(token)
        knowledge_revision = app.state.knowledge.metadata()["revision"] if settings.rag_enabled else 0
        prepared = await asyncio.to_thread(
            app.state.store.start, user, conversation, request_id,
            body.message, settings.model_timeout + 30,
            binding["revision"], binding["enabled"], knowledge_revision,
            order_capability.request_key if order_capability else "",
        )
        generator = stream_turn(
            app, conversation, request_id, body.message, user, token,
            prepared, request.is_disconnected, order_capability,
        )
        return StreamingResponse(generator, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    original_openapi = app.openapi

    def documented_openapi():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("schemas", {})["ErrorView"] = ErrorView.model_json_schema()
        for path, operations in schema["paths"].items():
            if not path.startswith("/ai/v1/"):
                continue
            for operation in operations.values():
                responses = operation.setdefault("responses", {})
                responses.pop("422", None)
                for status in (400, 401, 404, 409, 413, 429, 500, 502, 503, 504):
                    responses[str(status)] = {
                        "description": "Controlled JSON error before streaming starts",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorView"}}},
                    }
        return schema

    app.openapi = documented_openapi
    return app
