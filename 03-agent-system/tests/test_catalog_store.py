"""商品目录存储测试：种子幂等 / 持久化 / CRUD / 自动登记三重防护 / 启发式与价格提取。

全部离线；直跑本文件不污染真实 data/（每个用例独立临时库）。
"""
import tempfile
import unittest
from pathlib import Path

from agents.pre_sale.catalog_store import (
    SEED_PRODUCTS,
    ProductStore,
    detect_product,
    extract_price,
)


class TestExtractPrice(unittest.TestCase):
    def test_patterns(self):
        self.assertEqual(extract_price("售价 1299 元"), 1299.0)
        self.assertEqual(extract_price("价格：899"), 899.0)
        self.assertEqual(extract_price("仅需¥399.50"), 399.50)
        self.assertEqual(extract_price("￥399"), 399.0)
        self.assertEqual(extract_price("整机 599 元起"), 599.0)

    def test_none(self):
        self.assertIsNone(extract_price("续航 180 分钟，吸力 5000Pa"))
        self.assertIsNone(extract_price(""))
        self.assertIsNone(extract_price("无价格信息"))


class TestDetectProduct(unittest.TestCase):
    def test_positive_title_strips_keyword(self):
        d = detect_product("智能门锁 S1 参数", "指纹+密码开锁，价格 899 元")
        self.assertEqual(d["name"], "智能门锁 S1")
        self.assertEqual(d["price"], 899.0)
        self.assertTrue(d["specs"].startswith("指纹"))

    def test_positive_variants(self):
        for suffix in ("规格", "介绍", "手册", "说明书"):
            d = detect_product(f"智能净水器 W1 {suffix}", "大通量 RO 膜")
            self.assertEqual(d["name"], "智能净水器 W1", suffix)

    def test_negative_keywords(self):
        for title in ("售后服务说明", "退换货政策", "保修条款", "常见问题 FAQ", "配送服务公告"):
            self.assertIsNone(detect_product(title, "智能门锁 价格 899 元"), title)

    def test_keyword_only_title_falls_back_to_full(self):
        d = detect_product("参数", "价格 899 元")
        self.assertEqual(d["name"], "参数")  # strip 后为空 → 用全标题

    def test_content_fallback(self):
        d = detect_product("新品速览", "产品参数：额定功率 1200W，售价 499 元")
        self.assertEqual(d["name"], "新品速览")
        self.assertEqual(d["price"], 499.0)

    def test_content_fallback_requires_price(self):
        self.assertIsNone(detect_product("新品速览", "产品参数：额定功率 1200W"))

    def test_content_fallback_blocked_by_negative(self):
        self.assertIsNone(detect_product("新品速览", "产品参数如下；本服务最终解释权归商家"))

    # ---- 钉死现有测试 / 示例数据的行为（防止启发式误伤） ----
    def test_existing_fixtures_never_fire(self):
        # test_api.py / test_kb.py 的入库内容：无标题关键词且内容无「参数/规格」或无价格
        self.assertIsNone(detect_product("API 测试文档", "API 测试：智能门锁 S1 支持指纹开锁，保修一年。"))
        self.assertIsNone(detect_product("幂等测试文档", "智能音箱 M2 售价 399 元，支持智能家居联动。"))
        self.assertIsNone(detect_product("kb-test-门锁文档", "智能门锁 S1 售价 899 元，支持指纹开锁。"))
        self.assertIsNone(detect_product("faq", "问：滤网多少钱\n答：H13 滤网售价 199 元"))


class TestProductStore(unittest.TestCase):
    def setUp(self):
        # Windows 下 sqlite 句柄未释放会锁住文件，忽略清理残留
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.dir.name) / "products.db"
        self.store: ProductStore | None = None

    def tearDown(self):
        if self.store is not None:
            self.store.close()
        self.dir.cleanup()

    def _open(self) -> ProductStore:
        self.store = ProductStore(self.db)
        return self.store

    # ---- 种子 ----
    def test_seed_if_empty_idempotent(self):
        store = self._open()
        self.assertEqual(store.seed_if_empty(), len(SEED_PRODUCTS))
        self.assertEqual(store.seed_if_empty(), 0)  # 第二次不重复
        self.assertEqual(store.count(), 3)
        p1 = store.get("P001")
        self.assertEqual(p1["name"], "智能门锁 S1")
        self.assertEqual(p1["price"], 899.0)
        self.assertEqual(p1["stock"], 132)
        self.assertEqual(p1["origin"], "seed")

    def test_persistence_across_instances(self):
        store = self._open()
        store.seed_if_empty()
        store.create("智能空气炸锅 K1", specs="5.5L 大容量", price=1299.0, stock=8)
        again = ProductStore(self.db)
        names = [p["name"] for p in again.list()]
        again.close()
        self.assertIn("智能空气炸锅 K1", names)
        self.assertEqual(len(names), 4)

    # ---- 手动 CRUD ----
    def test_create_duplicate_name_raises(self):
        store = self._open()
        store.seed_if_empty()
        with self.assertRaises(ValueError):
            store.create("智能门锁 S1")

    def test_create_next_pid_monotonic_and_reuse(self):
        store = self._open()
        store.seed_if_empty()
        self.assertEqual(store.create("甲")["product_id"], "P004")
        self.assertEqual(store.create("乙")["product_id"], "P005")
        store.delete("P005")
        self.assertEqual(store.create("丙")["product_id"], "P005")  # 删最大号后号段复用

    def test_update_rename_collision_raises(self):
        store = self._open()
        store.seed_if_empty()
        with self.assertRaises(ValueError):
            store.update("P002", {"name": "智能门锁 S1"})
        entry = store.update("P002", {"price": 1699.0, "stock": 10})
        self.assertEqual((entry["price"], entry["stock"]), (1699.0, 10))
        self.assertEqual(entry["origin"], "manual")  # 手动编辑后转为 manual

    def test_update_missing_returns_none(self):
        store = self._open()
        store.seed_if_empty()
        self.assertIsNone(store.update("P999", {"price": 1.0}))
        self.assertIsNone(store.delete("P999"))

    # ---- 自动登记三重防护 ----
    def test_register_from_doc_creates_new(self):
        store = self._open()
        store.seed_if_empty()
        entry = store.register_from_doc(
            {"name": "智能净水器 W1", "specs": "RO 膜", "price": 1599.0}, "doc-1")
        self.assertEqual(entry["product_id"], "P004")
        self.assertEqual(entry["origin"], "doc")
        self.assertEqual(entry["stock"], 100)  # 默认库存，不显示缺货
        self.assertEqual(entry["source_doc_id"], "doc-1")

    def test_register_from_doc_dedupe_keeps_stock_category(self):
        store = self._open()
        store.seed_if_empty()
        entry = store.register_from_doc(
            {"name": "智能门锁 S1", "specs": "新款参数内容", "price": 899.0}, "doc-2")
        self.assertEqual(entry["product_id"], "P001")  # 同名更新，不新增
        self.assertEqual(entry["stock"], 132)          # 库存保留
        self.assertEqual(entry["category"], "智能安防")  # 分类保留
        self.assertEqual(entry["origin"], "doc")

    def test_register_from_doc_noop_when_unchanged(self):
        store = self._open()
        store.seed_if_empty()
        store.register_from_doc({"name": "智能门锁 S1", "specs": "同内容", "price": 899.0}, "doc-3")
        first = store.get("P001")
        store.register_from_doc({"name": "智能门锁 S1", "specs": "同内容", "price": 899.0}, "doc-3")
        second = store.get("P001")
        self.assertEqual(first["updated_at"], second["updated_at"])  # 重复入库零写入

    def test_register_from_doc_never_clobbers_manual(self):
        store = self._open()
        store.seed_if_empty()
        store.update("P001", {"price": 799.0})  # 用户手动改价
        entry = store.register_from_doc(
            {"name": "智能门锁 S1", "specs": "文档内容", "price": 899.0}, "doc-4")
        self.assertEqual(entry["price"], 799.0)  # manual 行不被覆盖

    def test_find_by_name_space_insensitive(self):
        store = self._open()
        store.seed_if_empty()
        self.assertEqual(store.find_by_name("智能门锁S1")["product_id"], "P001")
        self.assertIsNone(store.find_by_name("不存在"))


if __name__ == "__main__":
    unittest.main()
