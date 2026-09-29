from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from app.database import ALLOWED_TABLES, MAX_ROWS, QUERY_TIMEOUT_SECONDS, open_readonly_connection


FORBIDDEN_NODE_NAMES = {
    "Alter", "Attach", "Command", "Copy", "Create", "Delete", "Detach", "Drop",
    "Insert", "Into", "Merge", "Pragma", "Transaction", "TruncateTable", "Update", "Use",
}
BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "randomblob", "zeroblob"}


class UnsafeQuery(ValueError):
    pass


@dataclass
class QueryResult:
    sql: str
    tables: list[str]
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    duration_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "tables": self.tables,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
        }


def validate_sql(sql: str) -> tuple[str, list[str]]:
    if not sql or len(sql) > 5000:
        raise UnsafeQuery("SQL 不能为空，且长度不能超过 5000 个字符。")
    try:
        parsed = [tree for tree in sqlglot.parse(sql, read="sqlite") if tree is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeQuery("SQL 语法无法解析，请检查字段名和语法。") from exc
    if len(parsed) != 1:
        raise UnsafeQuery("只允许执行一条 SQL 语句。")

    tree = parsed[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeQuery("只允许 SELECT 查询。")
    if sum(1 for _ in tree.walk()) > 500:
        raise UnsafeQuery("SQL 结构过于复杂，请缩小查询范围。")
    for node in tree.walk():
        if node.__class__.__name__ in FORBIDDEN_NODE_NAMES:
            raise UnsafeQuery("查询包含写入或管理操作，已拒绝执行。")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if table.db or table.catalog or name not in ALLOWED_TABLES:
            raise UnsafeQuery(f"表 `{table.name}` 不在允许查询的数据表清单中。")
        tables.add(name)
    if not tables:
        raise UnsafeQuery("查询必须读取至少一张允许的数据表。")

    limit_node = tree.args.get("limit")
    if limit_node is None:
        tree = tree.limit(MAX_ROWS)
    else:
        limit_expression = limit_node.args.get("expression")
        limit_text = limit_expression.sql(dialect="sqlite") if limit_expression is not None else ""
        if not re.fullmatch(r"\d+", limit_text):
            raise UnsafeQuery("LIMIT 必须是固定的非负整数。")
        if int(limit_text) > MAX_ROWS:
            limit_node.set("expression", exp.Literal.number(MAX_ROWS))

    return tree.sql(dialect="sqlite"), sorted(tables)


def _authorizer(action: int, arg1: str | None, arg2: str | None, database: str | None, trigger: str | None) -> int:
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if (arg1 or "").lower() in ALLOWED_TABLES else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (arg2 or arg1 or "").lower()
        return sqlite3.SQLITE_DENY if function_name in BLOCKED_FUNCTIONS else sqlite3.SQLITE_OK
    allowed = {sqlite3.SQLITE_SELECT}
    if hasattr(sqlite3, "SQLITE_RECURSIVE"):
        allowed.add(sqlite3.SQLITE_RECURSIVE)
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def execute_readonly(sql: str) -> QueryResult:
    normalized, tables = validate_sql(sql)
    started = time.perf_counter()
    deadline = started + QUERY_TIMEOUT_SECONDS
    conn = open_readonly_connection()
    try:
        conn.set_authorizer(_authorizer)
        conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 1000)
        cursor = conn.execute(normalized)
        columns = [column[0] for column in cursor.description or []]
        raw_rows = cursor.fetchmany(MAX_ROWS + 1)
        truncated = len(raw_rows) > MAX_ROWS
        rows = [dict(row) for row in raw_rows[:MAX_ROWS]]
        return QueryResult(
            sql=normalized,
            tables=tables,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "interrupted" in message:
            raise UnsafeQuery("查询超过 1.2 秒执行上限，已中止。请添加时间范围或减少 JOIN。") from exc
        if "not authorized" in message:
            raise UnsafeQuery("数据库权限层拒绝了该操作。") from exc
        if "no such table" in message or "no such column" in message:
            raise UnsafeQuery("查询引用了不存在的数据表或字段，请先查看数据字典。") from exc
        raise UnsafeQuery(f"数据库未能执行该查询：{str(exc)[:220]}") from exc
    finally:
        conn.close()
