"""LangGraph tool loop. The model selects tools and Java owns business state."""
import asyncio
import json
import time
import uuid
from contextlib import aclosing
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .errors import AppError
from .inventory_analysis import analyze_inventory
from .purchase_proposal import grounded_fallback_args, is_purchase_request, proposal_reply, propose_purchase
from .purchase_risk import assess
from .tools import argument_summary, tool_schemas, validated_call


class AgentState(TypedDict, total=False):
    messages: list[dict]
    calls: list
    count: int
    tool_rounds: int
    repaired: bool
    missing_action_retried: bool
    products: dict
    search_terms: dict
    draft_result: dict | None
    answer: str
    deltas: list[str]
    retry: bool
    match_pages: dict
    analyses: dict


async def run_agent(app, messages, context_data, token, check_binding, order_capability=None):
    schemas = tool_schemas(order_capability is not None)
    allowed = {entry["function"]["name"] for entry in schemas}
    message = messages[-1]["content"]
    purchase_requested = is_purchase_request(message)

    async def agent_node(state):
        await check_binding()
        history = state["messages"]
        added = [{key: value for key, value in row.items() if key != "reasoning_content"}
                 for row in history[len(messages):]]
        if len(json.dumps(added, ensure_ascii=False)) > app.state.settings.context_char_limit + 32000:
            raise AppError(502, "TOOL_CONTEXT_LIMIT", "工具上下文过长，请缩小查询范围")
        text, calls, reasoning, deltas = "", [], None, []
        iterator = app.state.model.stream(history, context_data=context_data, tools=schemas)
        try:
            async for packet in iterator:
                if isinstance(packet, str):
                    if len(text) + len(packet) > app.state.settings.output_char_limit:
                        raise AppError(502, "MODEL_OUTPUT_LIMIT", "回答过长，请缩小问题范围")
                    text += packet
                    deltas.append(packet)
                else:
                    calls.extend(packet["tool_calls"])
                    reasoning = packet.get("reasoning_content", reasoning)
        except AppError:
            if not calls and not order_capability and not purchase_requested and not state.get("match_pages"):
                emit = get_stream_writer()
                for delta in deltas:
                    emit(delta)
            raise
        finally:
            await iterator.aclose()
        if not calls:
            draft = state.get("draft_result")
            if draft is not None:
                text = (f"已准备未付款草稿 {draft['draft']['draftId']}，请到我的草稿核对。"
                        if draft["ok"] else draft["message"])
            elif order_capability is not None:
                if not state.get("missing_action_retried"):
                    reminder = {"role": "user", "content": "请调用 prepare_order_draft 处理本轮已授权的精确商品和数量。"}
                    return {"calls": [], "messages": [*history, reminder], "missing_action_retried": True, "retry": True}
                raise AppError(502, "ORDER_TOOL_NOT_CALLED", "模型未执行订单准备工具")
            elif state.get("match_pages"):
                missing = sorted(state["match_pages"].keys() - state.get("analyses", {}).keys())
                if missing:
                    if state.get("missing_action_retried"):
                        raise AppError(502, "INVENTORY_ANALYSIS_INCOMPLETE", "库存已读取，模型未完成逐项匹配")
                    reminder = {"role": "user", "content": f"请为这些库存页逐项调用 analyze_inventory：{missing}"}
                    return {"calls": [], "messages": [*history, reminder], "missing_action_retried": True, "retry": True}
                analyses = state["analyses"].values()
                items = [item for page in analyses for item in page["items"]]
                matches = [f"{item['name']}（库存 {item['stock']}）" for item in items if item["matchesNeed"]]
                text = f"已逐项分析 {len(items)} 项库存。"
                text += "符合需求：" + "、".join(matches) + "。" if matches else "本轮未匹配到符合需求的商品。"
                if any(page["nextAfterId"] is not None and page["nextAfterId"] not in state["analyses"]
                       for page in analyses):
                    text += "目录还有未分析的页面。"
                text += "匹配基于药品常见用途，个人用药需另行核对。"
            elif purchase_requested:
                grounded = grounded_fallback_args(message, state["products"])
                if grounded and state["count"] < 6:
                    recovered = propose_purchase(grounded, message, state["products"], state["search_terms"])
                    if recovered["ok"]:
                        return {"calls": [("propose_purchase", grounded)], "runtime_recovery": True}
                if not state.get("missing_action_retried"):
                    reminder = {"role": "user", "content": "如原文指定商品，请先查实时库存，再生成购买清单。仅描述用途时请查库存并逐项匹配。"}
                    return {"calls": [], "messages": [*history, reminder], "missing_action_retried": True, "retry": True}
            return {"calls": [], "answer": text, "deltas": deltas, "retry": False}
        try:
            validated = [validated_call(call) for call in calls]
            for name, args in validated:
                if name not in allowed:
                    raise AppError(403, "ORDER_AUTHORIZATION_REQUIRED", "本轮未授权此工具")
                if name == "prepare_order_draft" and args["items"] != order_capability.items:
                    raise AppError(403, "ORDER_INTENT_MISMATCH", "商品或数量超出用户授权")
        except AppError as exc:
            if state.get("repaired"):
                raise
            reminder = {"role": "user", "content": "上一批工具未执行。" + exc.message + "。请按工具参数和本轮授权重新调用。"}
            return {"calls": [], "messages": [*history, reminder], "repaired": True, "retry": True}
        max_rounds = 6 if state.get("match_pages") else 3
        if state["count"] + len(validated) > 6 or state["tool_rounds"] >= max_rounds:
            raise AppError(502, "TOOL_CALL_LIMIT", "本轮工具调用次数达到上限，请缩小查询范围")
        assistant = {"role": "assistant", "content": "", "tool_calls": [
            {**({"id": call["id"]} if "id" in call else {}),
             "type": "function", "function": {"name": name, "arguments": args}}
            for call, (name, args) in zip(calls, validated)
        ]}
        if reasoning is not None:
            assistant["reasoning_content"] = reasoning
        return {"calls": validated, "messages": [*history, assistant], "answer": ""}

    async def tools_node(state):
        emit = get_stream_writer()
        products, terms = dict(state["products"]), dict(state["search_terms"])
        match_pages = dict(state.get("match_pages", {}))
        analyses = dict(state.get("analyses", {}))
        history, draft = list(state["messages"]), state.get("draft_result")
        preview = None
        for name, args in state["calls"]:
            await check_binding()
            call_id, started = str(uuid.uuid4()), time.monotonic()
            base = {"callId": call_id, "tool": name, "argumentsSummary": argument_summary(name, args)}
            delivered = asyncio.Event()
            emit(({"kind": "tool_started", "data": {**base, "status": "running"}}, delivered))
            await delivered.wait()
            await check_binding()
            if name == "analyze_inventory":
                result = analyze_inventory(args, match_pages.get(args["afterId"]))
                if result["ok"]:
                    analyses[args["afterId"]] = result["analysis"]
            elif name == "propose_purchase":
                result = (propose_purchase(args, message, products, terms) if purchase_requested else
                          {"ok": False, "code": "PURCHASE_INTENT_REQUIRED", "message": "本轮需要明确的购买请求"})
                if result["ok"]:
                    preview = result["proposal"]
                    risk = assess(context_data)
                    if any(not row.get("medicalEvidence") or row["quantity"] is None
                           or row["quantity"] > row["medicalEvidence"].get("maxUnitsPerOrder", 0)
                           for row in preview["items"]):
                        risk["automaticPurchaseAllowed"] = False
                    result["riskAssessment"] = risk
            elif name == "prepare_order_draft":
                if draft is None:
                    draft = await app.state.order_preparation.prepare(order_capability, args, call_id)
                result = draft
            else:
                result = await app.state.tools.execute(name, args, token, call_id)
                if result.get("ok") and "products" in result:
                    found = {row["id"]: row for row in result["products"]}
                    products.update(found)
                    if name == "search_medicines":
                        terms[args["name"]] = set(found)
                    if name == "list_inventory" and args["purpose"] == "match":
                        match_pages[args["afterId"]] = result
                        analyses.pop(args["afterId"], None)
            await check_binding()
            public_result = result
            if "products" in result:
                rows = [{key: value for key, value in row.items() if key != "medicalEvidence"}
                        for row in result["products"]]
                public_result = {**result, "products": rows}
            emit({"kind": "tool_result", "data": {**base, "status": "completed" if result["ok"] else "failed",
                  "durationMs": round((time.monotonic() - started) * 1000), "result": public_result}})
            if not state.get("runtime_recovery"):
                history.append({"role": "tool", "tool_name": name,
                                "content": json.dumps(public_result, ensure_ascii=False)})
        answer = proposal_reply(preview) if preview else ""
        if draft is not None:
            answer = (f"已准备未付款草稿 {draft['draft']['draftId']}，请到我的草稿核对。"
                      if draft["ok"] else draft["message"])
        return {"messages": history, "products": products, "search_terms": terms, "draft_result": draft,
                "match_pages": match_pages, "analyses": analyses,
                "count": state["count"] + len(state["calls"]), "tool_rounds": state["tool_rounds"] + 1,
                "answer": answer}

    def after_agent(state):
        if state["calls"]:
            return "tools"
        return "agent" if state.get("retry") else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent)
    graph.add_conditional_edges("tools", lambda state: END if state["answer"] else "agent")
    initial = {"messages": list(messages), "count": 0, "tool_rounds": 0, "products": {}, "search_terms": {}}
    stream = graph.compile().astream(initial, stream_mode=["updates", "custom"], config={"recursion_limit": 18})
    async with aclosing(stream):
        async for mode, update in stream:
            if mode == "custom":
                if isinstance(update, tuple):
                    event, delivered = update
                    yield event
                    delivered.set()
                else:
                    yield update
            elif update.get("tools", {}).get("answer"):
                yield update["tools"]["answer"]
            elif update.get("agent", {}).get("answer"):
                answer = update["agent"]["answer"]
                deltas = update["agent"]["deltas"]
                for delta in deltas if "".join(deltas) == answer else [answer]:
                    yield delta
