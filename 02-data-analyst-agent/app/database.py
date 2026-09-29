from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from typing import Any

from app.config import settings


ALLOWED_TABLES = {"orders", "order_items", "products", "customers"}
MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 1.2

SCHEMA: dict[str, list[dict[str, str]]] = {
    "orders": [
        {"name": "order_id", "type": "TEXT", "description": "订单编号"},
        {"name": "order_date", "type": "TEXT", "description": "下单日期，YYYY-MM-DD"},
        {"name": "customer_id", "type": "TEXT", "description": "顾客编号"},
        {"name": "status", "type": "TEXT", "description": "paid、shipped、delivered、cancelled、refunded"},
        {"name": "channel", "type": "TEXT", "description": "online、marketplace、offline"},
        {"name": "region", "type": "TEXT", "description": "销售区域"},
        {"name": "total_cents", "type": "INTEGER", "description": "订单实付金额，单位分"},
    ],
    "order_items": [
        {"name": "order_id", "type": "TEXT", "description": "订单编号"},
        {"name": "product_id", "type": "TEXT", "description": "商品编号"},
        {"name": "quantity", "type": "INTEGER", "description": "购买数量"},
        {"name": "unit_price_cents", "type": "INTEGER", "description": "成交单价，单位分"},
    ],
    "products": [
        {"name": "product_id", "type": "TEXT", "description": "商品编号"},
        {"name": "name", "type": "TEXT", "description": "商品名称"},
        {"name": "category", "type": "TEXT", "description": "商品品类"},
        {"name": "cost_cents", "type": "INTEGER", "description": "成本单价，单位分"},
    ],
    "customers": [
        {"name": "customer_id", "type": "TEXT", "description": "顾客编号"},
        {"name": "segment", "type": "TEXT", "description": "顾客类型"},
        {"name": "city", "type": "TEXT", "description": "所在城市"},
    ],
}

PRODUCTS = [
    ("P-001", "无线降噪耳机", "数码", 42000, 79900),
    ("P-002", "人体工学键盘", "数码", 26000, 49900),
    ("P-003", "便携显示器", "数码", 73000, 119900),
    ("P-004", "桌面护眼台灯", "家居", 18500, 39900),
    ("P-005", "折叠收纳箱", "家居", 7800, 16900),
    ("P-006", "旅行双肩包", "出行", 31000, 59900),
    ("P-007", "轻量保温杯", "出行", 9200, 21900),
    ("P-008", "咖啡手冲套装", "厨房", 24000, 48900),
    ("P-009", "空气炸锅", "厨房", 35500, 69900),
    ("P-010", "瑜伽垫", "运动", 8500, 19900),
    ("P-011", "弹力训练带", "运动", 4200, 9900),
    ("P-012", "书桌理线套装", "家居", 4900, 12900),
]


def initialize_database() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                cost_cents INTEGER NOT NULL,
                list_price_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                segment TEXT NOT NULL,
                city TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                order_date TEXT NOT NULL,
                customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                status TEXT NOT NULL,
                channel TEXT NOT NULL,
                region TEXT NOT NULL,
                total_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                order_id TEXT NOT NULL REFERENCES orders(order_id),
                product_id TEXT NOT NULL REFERENCES products(product_id),
                quantity INTEGER NOT NULL,
                unit_price_cents INTEGER NOT NULL,
                PRIMARY KEY (order_id, product_id)
            );
            CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_items_product ON order_items(product_id);
            """
        )
        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] > 0:
            return

        rng = random.Random(42)
        conn.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
            PRODUCTS,
        )
        cities = ["上海", "北京", "杭州", "成都", "广州", "武汉", "南京", "苏州"]
        segments = ["新客", "复购客", "会员"]
        customers = [
            (f"C-{index:03d}", rng.choices(segments, weights=[5, 4, 2])[0], rng.choice(cities))
            for index in range(1, 51)
        ]
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?)", customers)

        statuses = ["paid", "shipped", "delivered", "cancelled", "refunded"]
        channels = ["online", "marketplace", "offline"]
        regions = ["华东", "华北", "华南", "西南", "华中"]
        start_date = date(2026, 1, 1)
        days = max(1, (date.today() - start_date).days + 1)
        order_rows: list[tuple[Any, ...]] = []
        item_rows: list[tuple[Any, ...]] = []
        valid_products = [product for product in PRODUCTS]
        for index in range(1, 241):
            order_id = f"AN-{index:05d}"
            order_date = start_date + timedelta(days=rng.randrange(days))
            customer_id = rng.choice(customers)[0]
            status = rng.choices(statuses, weights=[12, 24, 50, 8, 6])[0]
            item_count = rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
            chosen = rng.sample(valid_products, item_count)
            line_items: list[tuple[str, str, int, int]] = []
            total = 0
            for product in chosen:
                quantity = rng.choices([1, 2, 3], weights=[8, 2, 1])[0]
                base_price = product[4]
                price = max(1, int(base_price * rng.uniform(0.88, 1.05)))
                line_items.append((order_id, product[0], quantity, price))
                total += quantity * price
            order_rows.append(
                (
                    order_id,
                    order_date.isoformat(),
                    customer_id,
                    status,
                    rng.choice(channels),
                    rng.choice(regions),
                    total,
                )
            )
            item_rows.extend(line_items)

        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", order_rows)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", item_rows)


def get_schema() -> dict[str, list[dict[str, str]]]:
    return SCHEMA


def open_readonly_connection() -> sqlite3.Connection:
    uri = f"{settings.database_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
