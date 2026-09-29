from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                product_name TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                status TEXT NOT NULL,
                purchased_at TEXT NOT NULL,
                delivered_at TEXT,
                is_used INTEGER NOT NULL DEFAULT 0,
                tracking_no TEXT
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_no TEXT UNIQUE,
                thread_id TEXT NOT NULL,
                order_id TEXT,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                UNIQUE(thread_id, category)
            );

            CREATE TABLE IF NOT EXISTS refund_requests (
                request_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                order_id TEXT NOT NULL REFERENCES orders(order_id),
                amount_cents INTEGER NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                customer_confirmed INTEGER NOT NULL DEFAULT 0,
                reviewer_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(thread_id, order_id)
            );

            CREATE TABLE IF NOT EXISTS refunds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE REFERENCES refund_requests(request_id),
                order_id TEXT NOT NULL REFERENCES orders(order_id),
                amount_cents INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_refunds_status ON refund_requests(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_logs(thread_id, id);
            """
        )

        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            today = date.today()
            seeds = [
                (
                    "ORD-2026-1001",
                    "林同学",
                    "桌面护眼台灯",
                    39900,
                    "delivered",
                    (today - timedelta(days=8)).isoformat(),
                    (today - timedelta(days=3)).isoformat(),
                    0,
                    "SF100000001",
                ),
                (
                    "ORD-2026-1002",
                    "周同学",
                    "无线降噪耳机",
                    89900,
                    "delivered",
                    (today - timedelta(days=20)).isoformat(),
                    (today - timedelta(days=12)).isoformat(),
                    0,
                    "YT200000002",
                ),
                (
                    "ORD-2026-1003",
                    "陈同学",
                    "人体工学键盘",
                    52900,
                    "shipped",
                    (today - timedelta(days=2)).isoformat(),
                    None,
                    0,
                    "JD300000003",
                ),
                (
                    "ORD-2026-1004",
                    "王同学",
                    "便携显示器",
                    119900,
                    "delivered",
                    (today - timedelta(days=6)).isoformat(),
                    (today - timedelta(days=2)).isoformat(),
                    1,
                    "SF400000004",
                ),
            ]
            conn.executemany(
                """INSERT INTO orders (
                    order_id, customer_name, product_name, amount_cents, status,
                    purchased_at, delivered_at, is_used, tracking_no
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                seeds,
            )


def _order_dict(row: sqlite3.Row) -> dict[str, Any]:
    status_labels = {"delivered": "已签收", "shipped": "运输中", "refunded": "已退款"}
    return {
        "order_id": row["order_id"],
        "customer_name": row["customer_name"],
        "product_name": row["product_name"],
        "amount_cents": row["amount_cents"],
        "amount": row["amount_cents"] / 100,
        "status": row["status"],
        "status_label": status_labels.get(row["status"], row["status"]),
        "purchased_at": row["purchased_at"],
        "delivered_at": row["delivered_at"],
        "is_used": bool(row["is_used"]),
        "tracking_no": row["tracking_no"],
    }


def get_order(order_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id.strip().upper(),)).fetchone()
    return _order_dict(row) if row else None


def list_demo_orders() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY order_id").fetchall()
    return [_order_dict(row) for row in rows]


def refund_eligibility(order_id: str) -> dict[str, Any]:
    order = get_order(order_id)
    if not order:
        return {"eligible": False, "reason": "没有找到这个订单，请核对订单号。", "order": None}
    if order["status"] == "refunded":
        return {"eligible": False, "reason": "该订单已经完成模拟退款。", "order": order}
    if order["status"] != "delivered" or not order["delivered_at"]:
        return {"eligible": False, "reason": "订单尚未签收，当前无法按七日无理由规则申请退货。", "order": order}
    delivered_days_ago = (date.today() - date.fromisoformat(order["delivered_at"])).days
    if delivered_days_ago > 7:
        return {"eligible": False, "reason": f"订单已签收 {delivered_days_ago} 天，超过七日无理由申请期限。", "order": order}
    if order["is_used"]:
        return {"eligible": False, "reason": "模拟订单标记为已使用，不符合七日无理由退货条件。", "order": order}
    return {
        "eligible": True,
        "reason": f"订单签收 {delivered_days_ago} 天，且商品未使用，符合模拟规则。",
        "order": order,
    }


def create_refund_request(thread_id: str, order_id: str, reason: str) -> dict[str, Any]:
    order_id = order_id.strip().upper()
    eligibility = refund_eligibility(order_id)
    if not eligibility["eligible"]:
        return {"eligible": False, "reason": eligibility["reason"], "order": eligibility["order"]}

    order = eligibility["order"]
    now = utc_now()
    request_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM refund_requests WHERE thread_id = ? AND order_id = ?",
            (thread_id, order_id),
        ).fetchone()
        if existing:
            if existing["status"] in {"awaiting_customer_confirmation", "awaiting_staff_approval", "approved"}:
                return {
                    "eligible": True,
                    "created": False,
                    "request_id": existing["request_id"],
                    "status": existing["status"],
                    "order": order,
                    "reason": existing["reason"],
                    "message": "已找到这个对话中现有的退款申请，不会重复创建。",
                }
            return {
                "eligible": False,
                "created": False,
                "request_id": existing["request_id"],
                "status": existing["status"],
                "order": order,
                "reason": existing["reason"],
                "message": "这个对话已经有该订单的退款申请，未重复创建。",
            }

        conn.execute(
            """INSERT INTO refund_requests (
                request_id, thread_id, order_id, amount_cents, reason, status,
                customer_confirmed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'awaiting_customer_confirmation', 0, ?, ?)""",
            (request_id, thread_id, order_id, order["amount_cents"], reason.strip()[:300] or "用户申请退款", now, now),
        )
        _insert_audit(
            conn,
            thread_id,
            "agent",
            "refund.proposed",
            {"request_id": request_id, "order_id": order_id, "amount_cents": order["amount_cents"]},
        )

    return {
        "eligible": True,
        "created": True,
        "request_id": request_id,
        "status": "awaiting_customer_confirmation",
        "order": order,
        "reason": reason.strip()[:300] or "用户申请退款",
        "message": "已准备模拟退款申请，等待用户确认。尚未执行退款。",
    }


def create_ticket(
    thread_id: str,
    order_id: str | None,
    category: str,
    summary: str,
    priority: str = "normal",
) -> dict[str, Any]:
    clean_order_id = (order_id or "").strip().upper() or None
    clean_category = category.strip()[:40] or "售后咨询"
    clean_summary = summary.strip()[:500] or "用户发起售后咨询"
    clean_priority = "high" if priority.lower() == "high" else "normal"
    if clean_order_id and not get_order(clean_order_id):
        return {"error": "order_not_found", "message": "没有找到这个订单，没有创建工单。"}

    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM tickets WHERE thread_id = ? AND category = ?",
            (thread_id, clean_category),
        ).fetchone()
        if existing:
            return {
                "ticket_no": existing["ticket_no"],
                "status": existing["status"],
                "created": False,
                "message": "这个对话已存在同类工单，没有重复创建。",
            }

        cursor = conn.execute(
            """INSERT INTO tickets (
                thread_id, order_id, category, summary, priority, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (thread_id, clean_order_id, clean_category, clean_summary, clean_priority, utc_now()),
        )
        ticket_id = cursor.lastrowid
        ticket_no = f"TK-{ticket_id:05d}"
        conn.execute("UPDATE tickets SET ticket_no = ? WHERE id = ?", (ticket_no, ticket_id))
        _insert_audit(
            conn,
            thread_id,
            "agent",
            "ticket.created",
            {"ticket_no": ticket_no, "order_id": clean_order_id, "category": clean_category},
        )

    return {"ticket_no": ticket_no, "status": "open", "created": True, "message": "售后工单已创建。"}


def _insert_audit(
    conn: sqlite3.Connection,
    thread_id: str,
    actor: str,
    event: str,
    details: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO audit_logs (thread_id, actor, event, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (thread_id, actor, event, json.dumps(details, ensure_ascii=False), utc_now()),
    )


def record_tool_event(thread_id: str, tool_name: str, details: dict[str, Any]) -> None:
    with connection() as conn:
        _insert_audit(conn, thread_id, "agent", f"tool.{tool_name}", details)


def get_refund_request(request_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT r.*, o.customer_name, o.product_name
               FROM refund_requests r JOIN orders o ON o.order_id = r.order_id
               WHERE r.request_id = ?""",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def get_thread_refund(thread_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT r.*, o.customer_name, o.product_name
               FROM refund_requests r JOIN orders o ON o.order_id = r.order_id
               WHERE r.thread_id = ?
               ORDER BY r.created_at DESC LIMIT 1""",
            (thread_id,),
        ).fetchone()
    return dict(row) if row else None


def list_pending_approvals() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT r.request_id, r.thread_id, r.order_id, r.amount_cents, r.reason,
                      r.status, r.created_at, o.customer_name, o.product_name
               FROM refund_requests r JOIN orders o ON o.order_id = r.order_id
               WHERE r.status = 'awaiting_staff_approval'
               ORDER BY r.created_at ASC"""
        ).fetchall()
    return [dict(row) for row in rows]


def record_customer_decision(request_id: str, approved: bool) -> None:
    next_status = "awaiting_staff_approval" if approved else "customer_rejected"
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT thread_id, status FROM refund_requests WHERE request_id = ?", (request_id,)).fetchone()
        if row and row["status"] == next_status:
            return
        if not row or row["status"] != "awaiting_customer_confirmation":
            raise ValueError("退款申请已不在等待用户确认状态。")
        conn.execute(
            """UPDATE refund_requests
               SET status = ?, customer_confirmed = ?, updated_at = ?
               WHERE request_id = ?""",
            (next_status, int(approved), utc_now(), request_id),
        )
        _insert_audit(
            conn,
            row["thread_id"],
            "customer",
            "refund.customer_confirmed" if approved else "refund.customer_cancelled",
            {"request_id": request_id},
        )


def record_staff_decision(request_id: str, approved: bool, note: str) -> None:
    next_status = "approved" if approved else "staff_rejected"
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT thread_id, status FROM refund_requests WHERE request_id = ?", (request_id,)).fetchone()
        if row and row["status"] == next_status:
            return
        if not row or row["status"] != "awaiting_staff_approval":
            raise ValueError("退款申请已不在等待人工审批状态。")
        clean_note = note.strip()[:300]
        conn.execute(
            "UPDATE refund_requests SET status = ?, reviewer_note = ?, updated_at = ? WHERE request_id = ?",
            (next_status, clean_note, utc_now(), request_id),
        )
        _insert_audit(
            conn,
            row["thread_id"],
            "staff",
            "refund.staff_approved" if approved else "refund.staff_rejected",
            {"request_id": request_id, "note": clean_note},
        )


def execute_mock_refund(request_id: str) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        request = conn.execute("SELECT * FROM refund_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not request:
            raise ValueError("没有找到退款申请。")
        existing = conn.execute("SELECT * FROM refunds WHERE request_id = ?", (request_id,)).fetchone()
        if existing:
            return {
                "refund_id": f"RF-{existing['id']:05d}",
                "order_id": existing["order_id"],
                "amount_cents": existing["amount_cents"],
                "status": existing["status"],
                "created": False,
            }
        if request["status"] != "approved" or not request["customer_confirmed"]:
            raise ValueError("退款尚未完成用户确认和人工审批，不能执行。")

        order = conn.execute(
            "SELECT status, delivered_at, is_used FROM orders WHERE order_id = ?",
            (request["order_id"],),
        ).fetchone()
        if not order or order["status"] != "delivered" or not order["delivered_at"]:
            block_reason = "订单状态已变化，模拟退款未执行。"
        elif order["is_used"] or (date.today() - date.fromisoformat(order["delivered_at"])).days > 7:
            block_reason = "订单已不符合模拟退款条件，模拟退款未执行。"
        else:
            block_reason = ""
        if block_reason:
            conn.execute(
                "UPDATE refund_requests SET status = 'execution_blocked', reviewer_note = ?, updated_at = ? WHERE request_id = ?",
                (block_reason, utc_now(), request_id),
            )
            _insert_audit(
                conn,
                request["thread_id"],
                "system",
                "refund.execution_blocked",
                {"request_id": request_id, "reason": block_reason},
            )
            return {
                "request_id": request_id,
                "order_id": request["order_id"],
                "amount_cents": request["amount_cents"],
                "status": "blocked",
                "reason": block_reason,
                "created": False,
            }

        cursor = conn.execute(
            """INSERT INTO refunds (request_id, order_id, amount_cents, status, created_at)
               VALUES (?, ?, ?, 'simulated_success', ?)""",
            (request_id, request["order_id"], request["amount_cents"], utc_now()),
        )
        refund_id = f"RF-{cursor.lastrowid:05d}"
        conn.execute("UPDATE orders SET status = 'refunded' WHERE order_id = ?", (request["order_id"],))
        conn.execute(
            "UPDATE refund_requests SET status = 'executed', updated_at = ? WHERE request_id = ?",
            (utc_now(), request_id),
        )
        _insert_audit(
            conn,
            request["thread_id"],
            "system",
            "refund.mock_executed",
            {"request_id": request_id, "refund_id": refund_id, "amount_cents": request["amount_cents"]},
        )
        return {
            "refund_id": refund_id,
            "order_id": request["order_id"],
            "amount_cents": request["amount_cents"],
            "status": "simulated_success",
            "created": True,
        }


def dashboard_metrics() -> dict[str, int]:
    with connection() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM refund_requests WHERE status = 'awaiting_staff_approval'"
        ).fetchone()[0]
        tickets = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'").fetchone()[0]
        refunds = conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]
        tool_calls = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event LIKE 'tool.%'").fetchone()[0]
    return {"pending_approvals": pending, "open_tickets": tickets, "simulated_refunds": refunds, "tool_calls": tool_calls}
