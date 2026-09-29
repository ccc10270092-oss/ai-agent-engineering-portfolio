from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.database import get_schema
from app.sql_safety import UnsafeQuery, execute_readonly
from app.config import settings


SYSTEM_PROMPT = """你是一个严谨的数据分析 Agent。请根据用户的问题分析演示电商数据库，并通过 run_readonly_query 工具执行查询。

规则：
- 只能使用给出的 SQLite 数据字典和表，不得臆造字段、表或结果。
- 使用 SQLite 语法。销售额字段以分存储，向用户展示金额时除以 100.0，并命名为 revenue。
- 收入分析默认排除 cancelled 和 refunded 订单；解释指标口径。
- SQL 必须是单条只读 SELECT，加入明确的时间或分类条件；返回用于回答问题的列，不要 SELECT *。
- 若 SQL 工具返回错误，可根据错误修正后再查询，最多尝试 3 次。
- 工具返回的行可能已被截断，分析时必须说明这一点。不要编造工具结果中没有的数值。
- 最终用中文总结结论和口径，指出主要数据趋势；数据不足时直接说明。
"""

TOOL = {
    "type": "function",
    "function": {
        "name": "run_readonly_query",
        "description": "验证并执行一条受限的只读 SQLite SELECT 查询，返回有限行数的数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "单条 SQLite SELECT 语句"},
                "explanation": {"type": "string", "description": "这条查询要回答什么问题"},
                "chart_type": {"type": "string", "enum": ["bar", "line", "none"]},
            },
            "required": ["sql", "explanation", "chart_type"],
            "additionalProperties": False,
        },
    },
}


class QueryToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1, max_length=5000)
    explanation: str = Field(min_length=1, max_length=300)
    chart_type: Literal["bar", "line", "none"]


def _schema_text() -> str:
    sections = []
    for table, columns in get_schema().items():
        rows = ", ".join(f"{column['name']} ({column['type']}: {column['description']})" for column in columns)
        sections.append(f"{table}: {rows}")
    return "\n".join(sections)


def _call_query(arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    try:
        parsed = QueryToolArguments.model_validate(arguments)
        result = execute_readonly(parsed.sql)
        result_payload = result.as_dict()
        trace = {
            "id": str(uuid.uuid4()),
            "kind": "tool",
            "name": "run_readonly_query",
            "status": "ok",
            "explanation": parsed.explanation,
            "sql": result.sql,
            "tables": result.tables,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result_payload["chart_type"] = parsed.chart_type
        return result_payload, trace
    except ValidationError:
        error = "工具参数未通过服务端校验。"
        sql = str(arguments.get("sql", ""))[:800]
        trace = {
            "id": str(uuid.uuid4()),
            "kind": "tool",
            "name": "run_readonly_query",
            "status": "rejected",
            "explanation": "参数校验失败",
            "sql": sql,
            "tables": [],
            "row_count": 0,
            "truncated": False,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "error": error,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return {"error": error}, trace
    except UnsafeQuery as exc:
        error = str(exc)
        trace = {
            "id": str(uuid.uuid4()),
            "kind": "tool",
            "name": "run_readonly_query",
            "status": "rejected",
            "explanation": str(arguments.get("explanation", ""))[:300],
            "sql": str(arguments.get("sql", ""))[:800],
            "tables": [],
            "row_count": 0,
            "truncated": False,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "error": error,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return {"error": error}, trace


def _demo_plan(question: str) -> tuple[str, str, str]:
    text = question.lower()
    active_orders = "o.status NOT IN ('cancelled', 'refunded')"
    if any(word in question for word in ("月", "趋势", "每月")) and any(word in question for word in ("销售", "营收", "收入", "金额")):
        sql = f"""SELECT strftime('%Y-%m', order_date) AS month,
                    ROUND(SUM(total_cents) / 100.0, 2) AS revenue
                 FROM orders AS o
                 WHERE {active_orders} AND order_date >= '2026-01-01'
                 GROUP BY month ORDER BY month"""
        return sql, "按月份汇总未取消、未退款订单的实付金额", "line"
    if any(word in question for word in ("品类", "类别", "分类")):
        sql = f"""SELECT p.category,
                    ROUND(SUM(i.quantity * i.unit_price_cents) / 100.0, 2) AS revenue
                 FROM order_items AS i
                 JOIN products AS p ON p.product_id = i.product_id
                 JOIN orders AS o ON o.order_id = i.order_id
                 WHERE {active_orders}
                 GROUP BY p.category ORDER BY revenue DESC LIMIT 10"""
        return sql, "比较各商品品类的成交金额", "bar"
    if any(word in question for word in ("地区", "区域", "省份")):
        sql = f"""SELECT region,
                    ROUND(SUM(total_cents) / 100.0, 2) AS revenue,
                    COUNT(*) AS order_count
                 FROM orders AS o WHERE {active_orders}
                 GROUP BY region ORDER BY revenue DESC"""
        return sql, "按销售区域汇总成交金额和订单数", "bar"
    if any(word in question for word in ("顾客", "客户", "会员")):
        sql = """SELECT c.segment, COUNT(DISTINCT c.customer_id) AS customer_count,
                    COUNT(o.order_id) AS order_count
                 FROM customers AS c LEFT JOIN orders AS o ON o.customer_id = c.customer_id
                 GROUP BY c.segment ORDER BY customer_count DESC"""
        return sql, "查看不同顾客分层的人数和订单数", "bar"
    sql = f"""SELECT p.name AS product, p.category,
                SUM(i.quantity) AS units_sold,
                ROUND(SUM(i.quantity * i.unit_price_cents) / 100.0, 2) AS revenue
             FROM order_items AS i
             JOIN products AS p ON p.product_id = i.product_id
             JOIN orders AS o ON o.order_id = i.order_id
             WHERE {active_orders}
             GROUP BY p.product_id ORDER BY revenue DESC LIMIT 8"""
    return sql, "列出成交额最高的商品", "bar"


def _demo_answer(question: str, result: dict[str, Any]) -> str:
    rows = result.get("rows", [])
    if not rows:
        return "查询已完成，但没有匹配的数据。"
    columns = result.get("columns", [])
    label_key = columns[0] if columns else ""
    number_key = next((key for key in columns[1:] if isinstance(rows[0].get(key), (int, float))), None)
    if not number_key:
        return f"查询已完成，共返回 {result.get('row_count', len(rows))} 行。"
    best = max(rows, key=lambda row: row.get(number_key) or 0)
    value = best.get(number_key)
    unit = " 元" if "revenue" in number_key else ""
    text = f"按演示数据统计，{best.get(label_key, '排名第一')}的{number_key}最高，为 {value}{unit}。"
    if len(rows) > 1:
        text += f"本次共比较 {len(rows)} 个分组。"
    if result.get("truncated"):
        text += "结果超过展示上限，当前结论仅基于前 100 行。"
    text += "\n演示规则 Agent 使用了预设查询模板；配置模型后会根据问题生成和修正 SQL。"
    return text


def analyze(question: str) -> dict[str, Any]:
    schema_text = _schema_text()
    trace: list[dict[str, Any]] = []
    latest_result: dict[str, Any] | None = None
    if not settings.api_key or settings.model == "your-openai-compatible-model":
        sql, explanation, chart_type = _demo_plan(question)
        trace.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "agent",
                "name": "演示查询规划器",
                "status": "demo",
                "explanation": "根据问题选择安全查询模板",
                "duration_ms": 0,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        latest_result, event = _call_query({"sql": sql, "explanation": explanation, "chart_type": chart_type})
        trace.append(event)
        return {
            "answer": _demo_answer(question, latest_result),
            "result": latest_result,
            "trace": trace,
            "mode": "demo",
        }

    client_kwargs: dict[str, Any] = {"api_key": settings.api_key, "timeout": 35, "max_retries": 2}
    if settings.base_url:
        client_kwargs["base_url"] = settings.base_url
    client = OpenAI(**client_kwargs)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n数据字典：\n{schema_text}"},
        {"role": "user", "content": question},
    ]
    answer = ""
    for _ in range(3):
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            tools=[TOOL],
            tool_choice="auto",
            temperature=0,
        )
        assistant = response.choices[0].message
        usage = response.usage
        trace.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "llm",
                "name": settings.model,
                "status": "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "usage": {
                    "input_tokens": getattr(usage, "prompt_tokens", None),
                    "output_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                },
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        tool_calls = assistant.tool_calls or []
        messages.append(
            {
                "role": "assistant",
                "content": assistant.content,
                "tool_calls": [call.model_dump(exclude_none=True) for call in tool_calls],
            }
        )
        if not tool_calls:
            answer = assistant.content or "模型没有返回可展示的分析结论。"
            break

        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments)
                latest_result, event = _call_query(arguments)
            except (json.JSONDecodeError, TypeError):
                latest_result = {"error": "工具参数不是有效 JSON。"}
                event = {
                    "id": str(uuid.uuid4()),
                    "kind": "tool",
                    "name": "run_readonly_query",
                    "status": "rejected",
                    "explanation": "工具参数解析失败",
                    "sql": "",
                    "tables": [],
                    "row_count": 0,
                    "truncated": False,
                    "duration_ms": 0,
                    "error": latest_result["error"],
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            trace.append(event)
            model_result = latest_result
            if model_result and model_result.get("rows") is not None:
                model_result = {**model_result, "rows": model_result["rows"][:20]}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(model_result, ensure_ascii=False, default=str),
                }
            )

    if not answer:
        answer = "已执行查询，但模型没有在 3 次调用内生成总结。请查看结果表和 SQL 轨迹。"
    return {"answer": answer, "result": latest_result, "trace": trace, "mode": "llm"}
