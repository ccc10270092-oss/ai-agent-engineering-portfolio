from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import database
from app.agent import build_agent, latest_reply, serialize_messages
from app.config import settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialize_database()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as checkpointer:
        app.state.agent = build_agent(checkpointer)
        yield


app = FastAPI(
    title="小满售后 Agent",
    description="带订单工具、政策检索与人工审批流程的售后服务 Agent 演示应用。",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class CustomerDecision(BaseModel):
    approved: bool


class StaffDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=300)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="需要有效的管理员令牌。")


def _graph_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _pending_payload(request: dict | None, status: str) -> dict | None:
    if not request:
        return None
    return {
        "request_id": request["request_id"],
        "order_id": request["order_id"],
        "customer_name": request["customer_name"],
        "product_name": request["product_name"],
        "amount_cents": request["amount_cents"],
        "amount": request["amount_cents"] / 100,
        "reason": request["reason"],
        "status": status,
        "created_at": request["created_at"],
    }


async def _thread_payload(thread_id: str, reply_override: str | None = None) -> dict:
    graph = app.state.agent
    snapshot = await graph.aget_state(_graph_config(thread_id))
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="没有找到这个对话。")

    values = snapshot.values
    request = database.get_thread_refund(thread_id)
    pending_confirmation = None
    pending_staff = None
    if request and request["status"] == "awaiting_customer_confirmation":
        pending_confirmation = _pending_payload(request, request["status"])
    elif request and request["status"] == "awaiting_staff_approval":
        pending_staff = _pending_payload(request, request["status"])

    reply = reply_override if reply_override is not None else latest_reply(values.get("messages", []))
    if pending_confirmation:
        reply = ""
    elif pending_staff and not reply:
        reply = "退款申请已确认，已进入售后人员审批队列。"

    return {
        "thread_id": thread_id,
        "messages": serialize_messages(values.get("messages", [])),
        "reply": reply,
        "pending_confirmation": pending_confirmation,
        "pending_staff_approval": pending_staff,
        "tool_events": values.get("tool_events", []),
        "waiting_for_input": bool(pending_confirmation or pending_staff),
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def public_config() -> dict:
    llm_ready = bool(settings.llm_api_key and settings.llm_model != "your-openai-compatible-model")
    return {
        "demo_mode": not llm_ready,
        "model": settings.llm_model if llm_ready else None,
        "app_name": "小满售后 Agent",
    }


@app.get("/api/demo/orders")
async def demo_orders() -> dict:
    return {"orders": database.list_demo_orders()}


@app.get("/api/dashboard")
async def dashboard() -> dict:
    return database.dashboard_metrics()


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="消息不能为空。")
    thread_id = request.thread_id or str(uuid.uuid4())
    active_refund = database.get_thread_refund(thread_id)
    if active_refund and active_refund["status"] in {"awaiting_customer_confirmation", "awaiting_staff_approval"}:
        raise HTTPException(status_code=409, detail="这个退款申请仍在审批流程中，请先完成确认或审批。")

    graph = app.state.agent
    try:
        await graph.ainvoke(
            {"messages": [HumanMessage(content=request.message.strip())]},
            _graph_config(thread_id),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent 执行失败：{str(exc)[:300]}") from exc
    return await _thread_payload(thread_id)


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str) -> dict:
    return await _thread_payload(thread_id)


@app.post("/api/threads/{thread_id}/customer-confirm")
async def customer_confirm(thread_id: str, decision: CustomerDecision) -> dict:
    request = database.get_thread_refund(thread_id)
    if not request or request["status"] != "awaiting_customer_confirmation":
        raise HTTPException(status_code=409, detail="这个对话当前没有等待用户确认的退款申请。")

    graph = app.state.agent
    try:
        await graph.ainvoke(
            Command(resume={"approved": decision.approved}),
            _graph_config(thread_id),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"恢复审批流程失败：{str(exc)[:300]}") from exc

    if decision.approved:
        return await _thread_payload(thread_id, "退款申请已确认，现已进入人工审批队列。")
    return await _thread_payload(thread_id)


@app.get("/api/admin/approvals", dependencies=[Depends(require_admin)])
async def admin_approvals() -> dict:
    approvals = database.list_pending_approvals()
    for item in approvals:
        item["amount"] = item["amount_cents"] / 100
    return {"approvals": approvals, "metrics": database.dashboard_metrics()}


@app.post("/api/admin/approvals/{request_id}", dependencies=[Depends(require_admin)])
async def decide_approval(request_id: str, decision: StaffDecision) -> dict:
    request = database.get_refund_request(request_id)
    if not request or request["status"] != "awaiting_staff_approval":
        raise HTTPException(status_code=409, detail="该申请已处理，或当前不在等待人工审批状态。")

    graph = app.state.agent
    approved = decision.decision == "approve"
    try:
        await graph.ainvoke(
            Command(resume={"approved": approved, "note": decision.note, "reviewer": "管理员演示账户"}),
            _graph_config(request["thread_id"]),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"恢复审批流程失败：{str(exc)[:300]}") from exc

    return await _thread_payload(request["thread_id"])


@app.get("/api/admin/metrics", dependencies=[Depends(require_admin)])
async def admin_metrics() -> dict:
    return database.dashboard_metrics()
