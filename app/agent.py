from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from operator import add
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import database, knowledge
from app.config import settings


SYSTEM_PROMPT = """你是「小满」售后服务 Agent，在一个模拟电商环境中为顾客提供帮助。

工作规则：
1. 用户问政策时，先调用 search_policy；回答只依据检索内容，并指出政策标题或条款编号。没有检索到时明确说明。
2. 用户问具体订单时，先调用 lookup_order；不能猜测物流、签收或商品状态。
3. 用户明确要求退货或退款时，必须先核对订单。只有 request_refund 工具返回可申请时，流程才会要求用户确认并进入人工审批。不得承诺申请一定通过。
4. 商品破损、错发、缺件、物流长时间未更新等需要跟进的问题，可以调用 create_support_ticket。创建前简短说明会登记工单。
5. 不得编造工单号、订单信息、政策或退款结果。退款由系统模拟，不能表示真实资金已退回。
6. 用清楚、友好的中文回答，先解决用户当前问题。不要透露内部推理过程。
"""


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "检索本地售后政策条款。用户询问退货、退款、物流、质量、保修等规则时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用于检索的中文关键词或问题"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "按订单号查询模拟订单、商品和物流状态。",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "例如 ORD-2026-1001"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_ticket",
            "description": "为商品问题、物流异常或复杂售后问题创建模拟工单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号；没有订单号时传空字符串"},
                    "category": {"type": "string", "description": "售后问题分类"},
                    "summary": {"type": "string", "description": "对用户问题的简短概括"},
                    "priority": {"type": "string", "enum": ["normal", "high"]},
                },
                "required": ["order_id", "category", "summary", "priority"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_refund",
            "description": "核验退货退款条件并准备一个模拟退款申请。申请只会进入待用户确认状态，不能执行退款。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "要申请退款的订单号"},
                    "reason": {"type": "string", "description": "退款原因"},
                },
                "required": ["order_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_events: Annotated[list[dict[str, Any]], add]
    pending_refund: NotRequired[dict[str, Any] | None]
    customer_confirmed: NotRequired[bool]
    staff_approved: NotRequired[bool]


class SearchPolicyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class LookupOrderArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=32, pattern=r"^ORD-[0-9]{4}-[0-9]{4}$")


class CreateTicketArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(default="", max_length=32)
    category: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=500)
    priority: Literal["normal", "high"]


class RefundArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=32, pattern=r"^ORD-[0-9]{4}-[0-9]{4}$")
    reason: str = Field(min_length=1, max_length=300)


def _tool_result_text(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _extract_order_id(text: str) -> str | None:
    match = re.search(r"ORD-[0-9]{4}-[0-9]{4}", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _offline_response(messages: list[AnyMessage]) -> AIMessage:
    last = messages[-1] if messages else None
    if isinstance(last, ToolMessage):
        try:
            result = json.loads(str(last.content))
        except (TypeError, json.JSONDecodeError):
            result = {"message": str(last.content)}

        if result.get("eligible") is False:
            explanation = result.get("message") or result.get("reason") or "不符合当前条件"
            return AIMessage(content=f"暂时不能准备退款申请：{explanation}。如你认为订单信息有误，请联系人工客服。")
        if result.get("order"):
            order = result["order"]
            tracking = order.get("tracking_no") or "暂无物流单号"
            return AIMessage(
                content=(
                    f"订单 {order['order_id']} 的商品是{order['product_name']}，当前状态为{order['status_label']}。"
                    f"物流单号：{tracking}。这是演示订单数据。"
                )
            )
        if result.get("results") is not None:
            if not result["results"]:
                return AIMessage(content="暂时没有检索到匹配的政策条款。你可以告诉我具体是退货、物流还是商品质量问题。")
            citations = "；".join(f"{item['title']}（{item['id']}）" for item in result["results"][:2])
            excerpts = "\n".join(f"- {item['title']}：{item['quote']}" for item in result["results"][:2])
            return AIMessage(content=f"根据本地演示政策：\n{excerpts}\n\n依据：{citations}。")
        if result.get("ticket_no"):
            return AIMessage(content=f"已创建售后工单 {result['ticket_no']}，当前状态为待处理。" + (f" {result.get('message', '')}"))
        if result.get("created") is True or result.get("status") == "awaiting_customer_confirmation":
            return AIMessage(content="退款申请已准备好，请先确认申请信息。通过确认后会进入人工审批。")
        return AIMessage(content=f"我查到了处理结果：{result.get('message', '请补充订单号或问题细节。')}")

    user_text = next((str(message.content) for message in reversed(messages) if isinstance(message, HumanMessage)), "")
    order_id = _extract_order_id(user_text)
    lower_text = user_text.lower()
    if order_id and any(word in user_text for word in ("退款", "退货", "退掉", "退换")):
        call = {"name": "request_refund", "args": {"order_id": order_id, "reason": user_text[:200]}, "id": str(uuid.uuid4()), "type": "tool_call"}
        return AIMessage(content="", tool_calls=[call])
    if order_id and any(word in user_text for word in ("破损", "坏了", "缺件", "错发", "投诉", "维修")):
        call = {
            "name": "create_support_ticket",
            "args": {
                "order_id": order_id,
                "category": "商品问题",
                "summary": user_text[:200],
                "priority": "high" if any(word in user_text for word in ("危险", "严重", "无法使用")) else "normal",
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
        return AIMessage(content="", tool_calls=[call])
    if not order_id and any(word in user_text for word in ("退款", "退货", "退掉", "退换")):
        return AIMessage(content="我可以帮你核对退货条件。请先提供订单号，例如 ORD-2026-1001；我会查询后再准备申请。")
    if order_id:
        call = {"name": "lookup_order", "args": {"order_id": order_id}, "id": str(uuid.uuid4()), "type": "tool_call"}
        return AIMessage(content="", tool_calls=[call])
    if any(word in user_text for word in ("政策", "规则", "条件", "保修", "几天", "物流", "签收", "退货", "退款")):
        call = {"name": "search_policy", "args": {"query": user_text}, "id": str(uuid.uuid4()), "type": "tool_call"}
        return AIMessage(content="", tool_calls=[call])
    if any(word in user_text for word in ("破损", "坏了", "缺件", "错发", "投诉", "维修")):
        call = {
            "name": "create_support_ticket",
            "args": {"order_id": "", "category": "售后问题", "summary": user_text[:200], "priority": "normal"},
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
        return AIMessage(content="", tool_calls=[call])
    if "hello" in lower_text or "你好" in user_text or "在吗" in user_text:
        return AIMessage(content="你好，我是小满售后 Agent。你可以试试查询订单、咨询退货政策，或申请一笔模拟退款。")
    return AIMessage(content="我可以帮你查订单、检索售后政策、登记售后工单或准备模拟退款申请。你可以发订单号（如 ORD-2026-1001）和想处理的问题。")


def build_agent(checkpointer: AsyncSqliteSaver):
    bound_model = None
    if settings.llm_api_key and settings.llm_model != "your-openai-compatible-model":
        model_kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "api_key": settings.llm_api_key,
            "temperature": 0,
            "timeout": 35,
            "max_retries": 2,
        }
        if settings.llm_base_url:
            model_kwargs["base_url"] = settings.llm_base_url
        bound_model = ChatOpenAI(**model_kwargs).bind_tools(TOOL_SCHEMAS, parallel_tool_calls=False)

    async def agent_node(state: AgentState, config: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        if bound_model:
            response = await bound_model.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]], config=config)
            usage = getattr(response, "usage_metadata", None) or {}
            event = {
                "id": str(uuid.uuid4()),
                "kind": "llm",
                "name": settings.llm_model,
                "status": "ok",
                "input_chars": sum(len(str(item.content)) for item in state["messages"]),
                "output_chars": len(str(response.content)),
                "usage": {
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        else:
            response = _offline_response(state["messages"])
            event = {
                "id": str(uuid.uuid4()),
                "kind": "llm",
                "name": "演示规则 Agent",
                "status": "demo",
                "input_chars": sum(len(str(item.content)) for item in state["messages"]),
                "output_chars": len(str(response.content)),
                "usage": None,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        return {"messages": [response], "tool_events": [event]}

    async def tool_node(state: AgentState, config: dict[str, Any]) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        assistant_message = state["messages"][-1]
        messages: list[ToolMessage] = []
        events: list[dict[str, Any]] = []
        pending_refund = state.get("pending_refund")
        customer_confirmed_update: bool | None = None
        staff_approved_update: bool | None = None

        for call in getattr(assistant_message, "tool_calls", []):
            name = call["name"]
            arguments = call.get("args", {})
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(_dispatch_tool, name, arguments, thread_id)
                if name == "request_refund" and result.get("eligible") and result.get("request_id"):
                    pending_refund = {
                        "request_id": result["request_id"],
                        "thread_id": thread_id,
                        "order_id": result["order"]["order_id"],
                        "product_name": result["order"]["product_name"],
                        "customer_name": result["order"]["customer_name"],
                        "amount_cents": result["order"]["amount_cents"],
                        "reason": result["reason"],
                        "tool_call_id": call["id"],
                    }
                    refund_status = result.get("status")
                    if refund_status == "awaiting_customer_confirmation":
                        customer_confirmed_update = False
                        staff_approved_update = False
                    elif refund_status == "awaiting_staff_approval":
                        customer_confirmed_update = True
                        staff_approved_update = False
                    elif refund_status == "approved":
                        customer_confirmed_update = True
                        staff_approved_update = True
            except Exception as exc:
                result = {"error": "tool_failed", "message": str(exc)[:300]}

            event = {
                "id": str(uuid.uuid4()),
                "kind": "tool",
                "name": name,
                "arguments": _safe_arguments(arguments),
                "result": result,
                "status": "error" if "error" in result else "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            await asyncio.to_thread(database.record_tool_event, thread_id, name, {"arguments": event["arguments"], "status": event["status"]})
            events.append(event)
            messages.append(ToolMessage(content=_tool_result_text(result), tool_call_id=call["id"]))

        update: dict[str, Any] = {"messages": messages, "tool_events": events}
        if pending_refund:
            update["pending_refund"] = pending_refund
        if customer_confirmed_update is not None:
            update["customer_confirmed"] = customer_confirmed_update
            update["staff_approved"] = staff_approved_update
        return update

    async def customer_confirmation_node(state: AgentState) -> dict[str, Any]:
        request = state["pending_refund"]
        approved = interrupt(
            {
                "type": "customer_confirmation",
                "title": "请确认退款申请",
                "message": "确认后，申请会进入人工审批；当前还没有执行退款。",
                "request_id": request["request_id"],
                "order_id": request["order_id"],
                "product_name": request["product_name"],
                "amount_cents": request["amount_cents"],
                "reason": request["reason"],
            }
        )
        customer_approved = bool(approved.get("approved")) if isinstance(approved, dict) else bool(approved)
        await asyncio.to_thread(database.record_customer_decision, request["request_id"], customer_approved)
        if customer_approved:
            return {"customer_confirmed": True}
        return {
            "customer_confirmed": False,
            "pending_refund": None,
            "messages": [AIMessage(content="已取消这笔模拟退款申请，没有执行退款。你还可以继续咨询政策或创建售后工单。")],
        }

    async def staff_approval_node(state: AgentState) -> dict[str, Any]:
        request = state["pending_refund"]
        decision = interrupt(
            {
                "type": "staff_approval",
                "title": "等待售后人员审批",
                "message": "顾客已确认申请，请核对订单与政策后审批。",
                "request_id": request["request_id"],
                "order_id": request["order_id"],
                "customer_name": request["customer_name"],
                "product_name": request["product_name"],
                "amount_cents": request["amount_cents"],
                "reason": request["reason"],
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        note = str(decision.get("note", "")) if isinstance(decision, dict) else ""
        await asyncio.to_thread(database.record_staff_decision, request["request_id"], approved, note)
        if approved:
            return {"staff_approved": True}
        return {
            "staff_approved": False,
            "pending_refund": None,
            "messages": [AIMessage(content="售后人员没有通过这笔模拟退款申请。申请未执行；如需了解原因，请联系人工客服。")],
        }

    async def execute_refund_node(state: AgentState) -> dict[str, Any]:
        request = state["pending_refund"]
        result = await asyncio.to_thread(database.execute_mock_refund, request["request_id"])
        if result["status"] == "blocked":
            message = result["reason"]
        else:
            amount = result["amount_cents"] / 100
            message = (
                f"用户已确认且人工审批通过。模拟退款 {result['refund_id']} 已创建，订单 {result['order_id']}，"
                f"金额 ¥{amount:.2f}。这只是演示环境中的状态变更，不涉及真实资金。"
            )
        event = {
            "id": str(uuid.uuid4()),
            "kind": "tool",
            "name": "execute_mock_refund",
            "arguments": {"request_id": request["request_id"]},
            "result": result,
            "status": "error" if result["status"] == "blocked" else "ok",
            "duration_ms": 0,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return {
            "messages": [AIMessage(content=message)],
            "tool_events": [event],
            "pending_refund": None,
            "staff_approved": True,
        }

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    builder.add_node("customer_confirmation", customer_confirmation_node)
    builder.add_node("staff_approval", staff_approval_node)
    builder.add_node("execute_refund", execute_refund_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _after_agent, {"tools": "tools", "end": END})
    builder.add_conditional_edges(
        "tools",
        _after_tools,
        {
            "customer_confirmation": "customer_confirmation",
            "staff_approval": "staff_approval",
            "execute_refund": "execute_refund",
            "agent": "agent",
        },
    )
    builder.add_conditional_edges(
        "customer_confirmation",
        _after_customer_confirmation,
        {"staff_approval": "staff_approval", "end": END},
    )
    builder.add_conditional_edges("staff_approval", _after_staff_approval, {"execute_refund": "execute_refund", "end": END})
    builder.add_edge("execute_refund", END)
    return builder.compile(checkpointer=checkpointer)


def _after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "end"


def _after_tools(state: AgentState) -> str:
    if not state.get("pending_refund"):
        return "agent"
    if state.get("staff_approved"):
        return "execute_refund"
    if state.get("customer_confirmed"):
        return "staff_approval"
    return "customer_confirmation"


def _after_customer_confirmation(state: AgentState) -> str:
    return "staff_approval" if state.get("customer_confirmed") else "end"


def _after_staff_approval(state: AgentState) -> str:
    return "execute_refund" if state.get("staff_approved") else "end"


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value)[:300] if isinstance(value, str) else value for key, value in arguments.items()}


def _dispatch_tool(name: str, arguments: dict[str, Any], thread_id: str) -> dict[str, Any]:
    schemas: dict[str, type[BaseModel]] = {
        "search_policy": SearchPolicyArguments,
        "lookup_order": LookupOrderArguments,
        "create_support_ticket": CreateTicketArguments,
        "request_refund": RefundArguments,
    }
    schema = schemas.get(name)
    if not schema:
        return {"error": "unknown_tool", "message": "不支持的工具调用。"}
    try:
        validated = schema.model_validate(arguments).model_dump()
    except ValidationError:
        return {"error": "invalid_tool_arguments", "message": "工具参数未通过服务端校验，没有执行操作。"}

    if name == "search_policy":
        return knowledge.search_policy(validated["query"])
    if name == "lookup_order":
        order = database.get_order(validated["order_id"])
        if not order:
            return {"error": "order_not_found", "message": "没有找到这个订单，请核对订单号。"}
        return {"order": order}
    if name == "create_support_ticket":
        return database.create_ticket(
            thread_id=thread_id,
            order_id=validated["order_id"],
            category=validated["category"],
            summary=validated["summary"],
            priority=validated["priority"],
        )
    if name == "request_refund":
        return database.create_refund_request(
            thread_id=thread_id,
            order_id=validated["order_id"],
            reason=validated["reason"],
        )
    return {"error": "unknown_tool", "message": "不支持的工具调用。"}


def latest_reply(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
                if text.strip():
                    return text
    return ""


def serialize_messages(messages: list[AnyMessage]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            role = "assistant"
        else:
            continue
        content = message.content
        if isinstance(content, str) and content.strip():
            result.append({"role": role, "content": content})
        elif isinstance(content, list):
            text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            if text.strip():
                result.append({"role": role, "content": text})
    return result
