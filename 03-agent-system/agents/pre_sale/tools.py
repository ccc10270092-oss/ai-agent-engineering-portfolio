"""工具接口与商品目录（对应设计 6.3 / PRD 6.3）。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app_core.models import RetrievedChunk

from .catalog_store import ProductStore


@dataclass
class ProductCatalog:
    """内存商品目录，供演示与测试。生产可替换为数据库查询。"""

    products: dict = field(default_factory=dict)
    stock: dict = field(default_factory=dict)

    @classmethod
    def sample(cls) -> "ProductCatalog":
        return cls(
            products={
                "P001": {
                    "name": "智能门锁 S1",
                    "specs": "指纹+密码+蓝牙三合一，续航 1 年，价格 899 元",
                    "category": "智能安防",
                },
                "P002": {
                    "name": "扫地机器人 R3",
                    "specs": "激光导航，5000Pa 吸力，续航 180 分钟，价格 1999 元",
                    "category": "清洁家电",
                },
                "P003": {
                    "name": "智能音箱 M2",
                    "specs": "语音助手，支持智能家居联动，价格 399 元",
                    "category": "智能家居",
                },
            },
            stock={"P001": 132, "P002": 45, "P003": 0},
        )


@dataclass
class ToolAction:
    name: str
    args: dict


class Tools:
    """售前咨询 Agent 可调用的工具集合。

    商品查询走持久化 ProductStore（SQLite）；未注入时退回内存种子库，
    保持独立构建 Tools 的旧行为。返回结构与旧内存目录实现保持一致。
    """

    def __init__(self, retriever, store: "ProductStore | None" = None):
        self.retriever = retriever
        self.store = store or ProductStore(":memory:")
        self.store.seed_if_empty()

    def call(self, action: ToolAction):
        if action.name == "search_knowledge":
            return self.search_knowledge(action.args.get("query", ""))
        if action.name == "get_product_info":
            return self.get_product_info(action.args.get("product_id", ""))
        if action.name == "get_stock":
            return self.get_stock(action.args.get("product_id", ""))
        raise ValueError(f"未知工具：{action.name}")

    def search_knowledge(self, query: str) -> list[RetrievedChunk]:
        return self.retriever.search(query)

    def get_product_info(self, product_id: str) -> dict:
        entry = self._lookup(product_id)
        if not entry:
            return {"error": f"未找到产品：{product_id}"}
        return {
            "product_id": entry["product_id"],
            "name": entry["name"],
            "specs": entry["specs"],
            "category": entry["category"],
        }

    def get_stock(self, product_id: str) -> dict:
        entry = self._lookup(product_id)
        if not entry:
            return {"error": f"未找到产品：{product_id}"}
        return {
            "product_id": entry["product_id"],
            "name": entry["name"],
            "stock": entry["stock"],
            "available": entry["stock"] > 0,
        }

    def _lookup(self, key: str) -> dict | None:
        """精确编号优先，其次名称模糊匹配（name in key 或 key in name）。"""
        products = self.store.list()
        for p in products:
            if p["product_id"] == key:
                return p
        for p in products:
            name = p["name"]
            if name in key or (key and key in name):
                return p
        return None


class ToolRouter:
    """规则路由（ReAct 的 thinking 环节）。

    首次调用返回一个动作，之后返回 None（表示进入 responding），
    使默认路径单跳终止；可在测试中注入自定义 router 验证多跳与超步。
    """

    STOCK_KEYS = ("库存", "有没有货", "缺货", "现货", "有货", "stock")
    PRODUCT_KEYS = ("参数", "规格", "型号", "价格", "多少钱", "配置", "详情")

    def __init__(self):
        self._acted = False

    def reset(self) -> None:
        self._acted = False

    def decide(self, query: str) -> ToolAction | None:
        if self._acted:
            return None
        self._acted = True
        q = (query or "").lower()
        if any(k in q for k in self.STOCK_KEYS):
            return ToolAction("get_stock", {"product_id": self._extract_key(query)})
        if any(k in q for k in self.PRODUCT_KEYS):
            return ToolAction("get_product_info", {"product_id": self._extract_key(query)})
        return ToolAction("search_knowledge", {"query": query})

    @staticmethod
    def _extract_key(query: str) -> str:
        # 边界用字母数字负向断言而非 \b：汉字是 word 字符，「查一下P001的参数」
        # 这类紧邻写法 \b 不成立会漏提取（与 rules.py 的 PII 边界同一坑）
        # \d{3,}：商品编号自动递增，P1000 及以后也要能提取
        m = re.search(r"(?<![0-9A-Za-z])[Pp]\d{3,}(?![0-9A-Za-z])", query or "")
        return m.group(0).upper() if m else query


def build_langchain_tools(tools: "Tools") -> list:
    """把三个业务工具封装为 LangChain ``Tool``（PRD 6.3 / BR-04.2）。

    满足「知识库检索工具封装为 LangChain Tool」的要求。离线 ReAct 决策仍走
    ``ToolRouter``（无需 LLM 即可跑通全链路）；接入真实模型后，可将本函数返回的
    工具列表绑定给 LangGraph 的 tool-calling 节点做自主决策。
    """
    from langchain_core.tools import tool

    @tool
    def search_knowledge(query: str) -> str:
        """在知识库中检索与 query 相关的片段，返回命中的文本。"""
        chunks = tools.search_knowledge(query)
        return "\n---\n".join(c.text for c in chunks) or "（未命中）"

    @tool
    def get_product_info(product_id: str) -> str:
        """按产品 ID 查询产品的参数与规格。"""
        return json.dumps(tools.get_product_info(product_id), ensure_ascii=False)

    @tool
    def get_stock(product_id: str) -> str:
        """按产品 ID 查询库存与是否有货。"""
        return json.dumps(tools.get_stock(product_id), ensure_ascii=False)

    return [search_knowledge, get_product_info, get_stock]