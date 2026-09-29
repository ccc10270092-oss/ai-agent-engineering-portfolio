"""商品目录存储：SQLite 持久化商品（编号 / 名称 / 参数 / 分类 / 价格 / 库存）。

替代 tools.py 中硬编码的 ProductCatalog.sample()（后者保留作向后兼容与种子参照）。
支撑：
- 内容生成页 / 售前 Agent 工具（get_product_info / get_stock）读取动态商品列表；
- 知识文档入库时按标题启发式自动登记商品（detect_product + register_from_doc）；
- 商品管理（新增 / 编辑 / 删除），手动编辑过的商品不被文档登记覆盖（origin=manual）。

origin 语义：seed=内置种子 / doc=知识文档自动登记 / manual=手动创建或编辑。
删除知识文档不会删除已登记的商品（两者独立管理）。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app_core.logger import get_logger

log = get_logger("pre_sale.catalog_store")

_COLS = (
    "product_id, name, specs, category, price, stock, "
    "origin, source_doc_id, created_at, updated_at"
)

# 内置种子（与 tools.ProductCatalog.sample() 保持一致；价格显式写死，避免种子期跑正则）
SEED_PRODUCTS = [
    {"product_id": "P001", "name": "智能门锁 S1",
     "specs": "指纹+密码+蓝牙三合一，续航 1 年，价格 899 元",
     "category": "智能安防", "price": 899.0, "stock": 132},
    {"product_id": "P002", "name": "扫地机器人 R3",
     "specs": "激光导航，5000Pa 吸力，续航 180 分钟，价格 1999 元",
     "category": "清洁家电", "price": 1999.0, "stock": 45},
    {"product_id": "P003", "name": "智能音箱 M2",
     "specs": "语音助手，支持智能家居联动，价格 399 元",
     "category": "智能家居", "price": 399.0, "stock": 0},
]

# ---- 自动登记启发式（标题为主，内容兜底） ----
_NEGATIVE_KEYS = ("售后", "服务", "政策", "条款", "退换", "保修", "faq", "常见问题", "协议", "公告", "通知")
_POSITIVE_KEYS = ("参数", "规格", "介绍", "手册", "说明书")
_PRICE_PATTERNS = (
    r"售价\s*[:：]?\s*(\d+(?:\.\d+)?)",
    r"价格\s*[:：为]?\s*(\d+(?:\.\d+)?)",
    r"[¥￥]\s*(\d+(?:\.\d+)?)",
    r"(\d+(?:\.\d+)?)\s*元",
)


def extract_price(text: str) -> float | None:
    """从文本提取第一个价格；无价格返回 None。"""
    for pattern in _PRICE_PATTERNS:
        m = re.search(pattern, text or "")
        if m:
            return float(m.group(1))
    return None


def detect_product(title: str, content: str) -> dict | None:
    """判断一篇知识文档是否是产品文档，是则返回登记信息 {name, specs, price}。

    规则（保守取向，误登记可在商品管理中删除）：
    1. 标题命中负向词（售后/服务/政策…）→ 不是产品；
    2. 标题命中正向词（参数/规格/介绍/手册/说明书）→ 是，名称=标题去掉尾部关键词；
    3. 兜底：内容含「参数|规格」且能提取价格且无负向词 → 是，名称=全标题。
    """
    title = (title or "").strip()
    content = content or ""
    low = title.lower()
    if not title or any(k in low for k in _NEGATIVE_KEYS):
        return None

    name = None
    if any(k in title for k in _POSITIVE_KEYS):
        name = re.sub(
            r"[\s\-·—:_|、,，]*(" + "|".join(_POSITIVE_KEYS) + r")+$", "", title
        ).strip() or title
    elif any(k in content for k in ("参数", "规格")) and extract_price(content) is not None \
            and not any(k in content.lower() for k in _NEGATIVE_KEYS):
        name = title
    if not name:
        return None
    return {"name": name, "specs": content.strip()[:100], "price": extract_price(content)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_entry(row: tuple) -> dict:
    return {
        "product_id": row[0],
        "name": row[1],
        "specs": row[2],
        "category": row[3],
        "price": row[4],
        "stock": row[5],
        "origin": row[6],
        "source_doc_id": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "available": int(row[5]) > 0,
    }


class ProductStore:
    """商品目录（SQLite 单表，自带连接 / 锁 / 逐操作 commit）。"""

    def __init__(self, db_path: str | Path = "data/products.db"):
        path = str(db_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS products "
            "(product_id TEXT PRIMARY KEY, name TEXT, specs TEXT DEFAULT '', "
            "category TEXT DEFAULT '', price REAL, stock INTEGER DEFAULT 100, "
            "origin TEXT DEFAULT 'seed', source_doc_id TEXT DEFAULT '', "
            "created_at TEXT, updated_at TEXT)"
        )
        self.conn.commit()

    def seed_if_empty(self) -> int:
        """库为空时写入内置种子（幂等），返回种子条数（已非空返回 0）。"""
        with self._lock:
            if self._count_locked() > 0:
                return 0
            now = _now()
            self.conn.executemany(
                f"INSERT INTO products({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(p["product_id"], p["name"], p["specs"], p["category"], p["price"],
                  p["stock"], "seed", "", now, now) for p in SEED_PRODUCTS],
            )
            self.conn.commit()
        return len(SEED_PRODUCTS)

    def get(self, product_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {_COLS} FROM products WHERE product_id = ?", (product_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def find_by_name(self, name: str) -> dict | None:
        """按名称查找（精确或去空格相等，兼容「智能门锁S1」/「智能门锁 S1」）。"""
        key = (name or "").strip()
        with self._lock:
            rows = self.conn.execute(
                f"SELECT {_COLS} FROM products WHERE name = ? OR replace(name,' ','') = ?",
                (key, key.replace(" ", "")),
            ).fetchall()
        return _row_to_entry(rows[0]) if rows else None

    def list(self) -> list[dict]:
        """按编号正序返回全部商品（含 available 派生字段）。"""
        with self._lock:
            rows = self.conn.execute(
                f"SELECT {_COLS} FROM products ORDER BY product_id"
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._count_locked()

    def register_from_doc(self, detected: dict, doc_id: str) -> dict:
        """知识文档自动登记：同名更新（保库存/分类），否则新建。

        三重防护：同名去重更新；内容未变跳过写入（幂等，不抖动 updated_at）；
        手动管理过的商品（origin=manual）永不被文档覆盖。
        """
        name, specs, price = detected["name"], detected["specs"], detected.get("price")
        with self._lock:
            existing = self._find_by_name_locked(name)
            if existing:
                if existing["origin"] == "manual":
                    return existing
                if (existing["specs"] == specs and existing["price"] == price
                        and existing["source_doc_id"] == doc_id):
                    return existing  # 重复入库同一文档，零写入
                self.conn.execute(
                    "UPDATE products SET specs=?, price=?, source_doc_id=?, "
                    "origin='doc', updated_at=? WHERE product_id=?",
                    (specs, price, doc_id, _now(), existing["product_id"]),
                )
                self.conn.commit()
                return self._get_locked(existing["product_id"])
            pid = self._next_pid_locked()
            now = _now()
            self.conn.execute(
                f"INSERT INTO products({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, name, specs, "", price, 100, "doc", doc_id, now, now),
            )
            self.conn.commit()
            entry = self._get_locked(pid)
        log.info(f"检测到产品文档，已自动登记商品 {pid}「{name}」")
        return entry

    def create(self, name: str, specs: str = "", category: str = "",
               price: float | None = None, stock: int = 100) -> dict:
        """手动新增商品（origin=manual）；同名抛 ValueError。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("商品名称不能为空")
        with self._lock:
            if self._find_by_name_locked(name):
                raise ValueError(f"同名商品已存在：{name}")
            pid = self._next_pid_locked()
            now = _now()
            self.conn.execute(
                f"INSERT INTO products({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, name, specs, category, price, stock, "manual", "", now, now),
            )
            self.conn.commit()
            return self._get_locked(pid)

    def update(self, product_id: str, fields: dict) -> dict | None:
        """手动编辑商品（origin=manual）；改名撞他人名称抛 ValueError。"""
        allowed = ("name", "specs", "category", "price", "stock")
        sets, vals = [], []
        for key in allowed:
            if key in fields and fields[key] is not None:
                sets.append(f"{key}=?")
                vals.append(fields[key])
        if not sets:
            return self.get(product_id)
        new_name = (fields.get("name") or "").strip()
        with self._lock:
            existing = self._get_locked(product_id)
            if not existing:
                return None
            if new_name and new_name != existing["name"]:
                other = self._find_by_name_locked(new_name)
                if other and other["product_id"] != product_id:
                    raise ValueError(f"同名商品已存在：{new_name}")
            sets += ["origin='manual'", "updated_at=?"]
            vals += [_now(), product_id]
            self.conn.execute(
                f"UPDATE products SET {', '.join(sets)} WHERE product_id=?", vals
            )
            self.conn.commit()
            return self._get_locked(product_id)

    def delete(self, product_id: str) -> dict | None:
        """删除商品，返回被删条目；不存在返回 None。"""
        with self._lock:
            existing = self._get_locked(product_id)
            if not existing:
                return None
            self.conn.execute("DELETE FROM products WHERE product_id=?", (product_id,))
            self.conn.commit()
        return existing

    def close(self) -> None:
        """关闭连接（测试用；Windows 下未关闭会锁住库文件）。"""
        with self._lock:
            self.conn.close()

    # ---- 锁内私有助手（调用方必须已持锁） ----
    def _count_locked(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])

    def _get_locked(self, product_id: str) -> dict | None:
        row = self.conn.execute(
            f"SELECT {_COLS} FROM products WHERE product_id = ?", (product_id,)
        ).fetchone()
        return _row_to_entry(row) if row else None

    def _find_by_name_locked(self, name: str) -> dict | None:
        key = (name or "").strip()
        row = self.conn.execute(
            "SELECT " + _COLS + " FROM products WHERE name = ? OR replace(name,' ','') = ?",
            (key, key.replace(" ", "")),
        ).fetchone()
        return _row_to_entry(row) if row else None

    def _next_pid_locked(self) -> str:
        """最大数字编号 +1（P004…；删掉最大号后号段可复用）。"""
        rows = self.conn.execute("SELECT product_id FROM products").fetchall()
        mx = 0
        for (pid,) in rows:
            m = re.fullmatch(r"P(\d+)", pid or "")
            if m:
                mx = max(mx, int(m.group(1)))
        return f"P{mx + 1:03d}"
