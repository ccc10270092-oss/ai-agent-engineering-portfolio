"""API 网关测试（模块 F）：REST 接口在离线 Mock 模式下端到端可跑通。

覆盖会话、知识入库/检索/删除/清空/文件上传、问答、商品目录、内容生成
后台任务、数据管道，与 run_tests.py 强制离线策略一致（不触网、零花费）。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 直跑本文件（不经 run_tests.py）时同样强制离线 + 知识库指向临时目录。
# 必须在 import api.main（触发 System 单例构建）之前设置。
for _key in ("LLM_API_KEY", "LLM_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ[_key] = ""
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["RETRIEVAL_VECTOR_BACKEND"] = "simple"
_api_test_data = tempfile.mkdtemp(prefix="agent-system-api-tests-")
os.environ["RETRIEVAL_FTS_DB"] = os.path.join(_api_test_data, "fts.db")
os.environ["RETRIEVAL_DOCS_DB"] = os.path.join(_api_test_data, "docs.db")
os.environ["RETRIEVAL_CHROMA_PATH"] = os.path.join(_api_test_data, "chroma")
os.environ["PRODUCTS_DB"] = os.path.join(_api_test_data, "products.db")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)


def _wait_task(task_id: str, timeout: float = 30.0) -> dict:
    """轮询内容生成任务直至完成（Mock 模式下毫秒级返回）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/content/tasks/{task_id}").json()
        if task["status"] != "running":
            return task
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 超时未完成")


class TestHealthAndStats(unittest.TestCase):
    def test_health_offline_mock(self):
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["llm_mode"], "mock")  # run_tests 强制清空 Key
        self.assertIn("retrieval", body)
        # 向量模式展示（测试环境强制哈希离线）
        self.assertEqual(body["embedding"]["mode"], "hash")
        self.assertFalse(body["embedding"]["fallback"])

    def test_stats_shape(self):
        body = client.get("/api/stats").json()
        for key in (
            "total_docs",
            "total_chunks",
            "total_sessions",
            "total_messages",
            "total_tasks",
        ):
            self.assertIn(key, body)


class TestSessions(unittest.TestCase):
    def test_create_list_history(self):
        created = client.post("/api/sessions", json={"user_id": "tester"}).json()
        self.assertTrue(created["session_id"])
        self.assertEqual(created["status"], "active")

        listed = client.get("/api/sessions").json()
        self.assertTrue(any(s["session_id"] == created["session_id"] for s in listed))

        history = client.get(f"/api/sessions/{created['session_id']}/history").json()
        self.assertEqual(history, [])

    def test_history_serializes_message_fields(self):
        created = client.post("/api/sessions").json()
        sid = created["session_id"]
        client.post("/api/ask", json={"session_id": sid, "query": "售后政策是什么？"})
        history = client.get(f"/api/sessions/{sid}/history").json()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertIn("created_at", history[0])  # datetime 已转 isoformat


class TestKnowledge(unittest.TestCase):
    def test_ingest_and_search(self):
        resp = client.post(
            "/api/knowledge/ingest",
            json={
                "title": "API 测试文档",
                "content": "API 测试：智能门锁 S1 支持指纹开锁，保修一年。",
                "source": "测试",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["chunks"], 1)

        hits = client.post(
            "/api/knowledge/search", json={"query": "门锁 指纹"}
        ).json()
        self.assertTrue(hits)
        self.assertIn("final_score", hits[0])
        self.assertIn("rank", hits[0])

    def test_sample_load(self):
        body = client.post("/api/knowledge/sample").json()
        self.assertEqual(len(body["entries"]), 4)
        self.assertGreaterEqual(body["total_chunks"], 4)

    def test_ingest_validation(self):
        resp = client.post("/api/knowledge/ingest", json={"title": "", "content": "x"})
        self.assertEqual(resp.status_code, 422)

    def test_ingest_idempotent_and_delete(self):
        payload = {
            "title": "幂等测试文档",
            "content": "智能音箱 M2 售价 399 元，支持智能家居联动。",
            "source": "测试",
        }
        first = client.post("/api/knowledge/ingest", json=payload).json()
        second = client.post("/api/knowledge/ingest", json=payload).json()
        self.assertEqual(first["entry"]["doc_id"], second["entry"]["doc_id"])
        same = [
            d for d in client.get("/api/knowledge").json()["docs"]
            if d["title"] == "幂等测试文档"
        ]
        self.assertEqual(len(same), 1)  # 重复入库覆盖不累积

        doc_id = first["entry"]["doc_id"]
        self.assertEqual(client.delete(f"/api/knowledge/{doc_id}").status_code, 200)
        self.assertFalse(any(
            d["doc_id"] == doc_id for d in client.get("/api/knowledge").json()["docs"]
        ))
        self.assertEqual(client.delete(f"/api/knowledge/{doc_id}").status_code, 404)

    def test_clear(self):
        client.post(
            "/api/knowledge/ingest",
            json={"title": "清空测试文档", "content": "清空知识库的测试内容。"},
        )
        body = client.post("/api/knowledge/clear").json()
        self.assertGreaterEqual(body["cleared_docs"], 1)
        listed = client.get("/api/knowledge").json()
        self.assertEqual(listed["total_docs"], 0)
        self.assertEqual(listed["total_chunks"], 0)


class TestKnowledgeUpload(unittest.TestCase):
    def test_upload_txt(self):
        resp = client.post(
            "/api/knowledge/upload",
            files={
                "file": (
                    "上传测试.txt",
                    "智能门锁 S1 支持指纹开锁，售价 899 元。".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreaterEqual(body["chunks"], 1)
        self.assertEqual(body["entry"]["title"], "上传测试")
        self.assertIn("文件上传", body["entry"]["source"])

    def test_upload_csv_faq_then_search(self):
        csv_data = "问题,回答\n保修多久,整机保修一年，全国联保。\n".encode("utf-8")
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("faq.csv", csv_data, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        hits = client.post("/api/knowledge/search", json={"query": "保修"}).json()
        self.assertTrue(hits)

    def test_upload_rejects_bad_suffix(self):
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("evil.exe", b"whatever", "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_empty_file(self):
        resp = client.post(
            "/api/knowledge/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        self.assertEqual(resp.status_code, 400)


class TestAsk(unittest.TestCase):
    def test_ask_returns_agent_answer(self):
        sid = client.post("/api/sessions").json()["session_id"]
        resp = client.post(
            "/api/ask", json={"session_id": sid, "query": "智能门锁 S1 的价格？"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("answer", body)
        self.assertIn("trace", body)
        self.assertIn("degraded", body)
        self.assertFalse(body["degraded"])  # Mock 模式不降级
        self.assertTrue(body["trace"])  # ReAct 轨迹非空

    def test_products_endpoint(self):
        products = client.get("/api/products").json()
        self.assertEqual(len(products), 3)
        p001 = next(p for p in products if p["product_id"] == "P001")
        self.assertEqual(p001["name"], "智能门锁 S1")
        self.assertTrue(p001["available"])

    def test_sample_keeps_catalog_at_three(self):
        """/sample 重复载入 4 篇示例文档：3 篇产品文档同名去重更新，商品数恒为 3。"""
        for _ in range(2):
            client.post("/api/knowledge/sample")
        products = client.get("/api/products").json()
        self.assertEqual(len(products), 3)  # 顺序无关性钉子
        p001 = next(p for p in products if p["product_id"] == "P001")
        self.assertEqual(p001["name"], "智能门锁 S1")
        self.assertEqual(p001["stock"], 132)      # 库存不被文档更新
        self.assertEqual(p001["category"], "智能安防")


class TestProducts(unittest.TestCase):
    """商品目录 CRUD + 文档入库自动登记（启发式）。"""

    SEED_IDS = {"P001", "P002", "P003"}

    def tearDown(self):
        # 清理自建商品与自建文档，保证 test_products_endpoint 的 len==3 恒成立
        for p in client.get("/api/products").json():
            if p["product_id"] not in self.SEED_IDS:
                client.delete(f"/api/products/{p['product_id']}")
        for d in client.get("/api/knowledge").json()["docs"]:
            if d["source"] == "商品目录测试":
                client.delete(f"/api/knowledge/{d['doc_id']}")

    def _ingest(self, title, content):
        return client.post(
            "/api/knowledge/ingest",
            json={"title": title, "content": content, "source": "商品目录测试"},
        ).json()

    def test_crud_cycle(self):
        created = client.post(
            "/api/products",
            json={"name": "测试加湿器 H1", "specs": "5L 水箱", "category": "小家电",
                  "price": 249.0, "stock": 6},
        )
        self.assertEqual(created.status_code, 200)
        entry = created.json()
        pid = entry["product_id"]
        self.assertEqual(entry["origin"], "manual")
        self.assertIn(pid, [p["product_id"] for p in client.get("/api/products").json()])

        dup = client.post("/api/products", json={"name": "测试加湿器 H1"})
        self.assertEqual(dup.status_code, 400)

        updated = client.put(f"/api/products/{pid}", json={"price": 199.0, "stock": 0})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["price"], 199.0)
        self.assertFalse(updated.json()["available"])

        rename = client.put(f"/api/products/{pid}", json={"name": "智能门锁 S1"})
        self.assertEqual(rename.status_code, 400)  # 改名撞种子商品

        self.assertEqual(client.delete(f"/api/products/{pid}").status_code, 200)
        self.assertEqual(client.delete(f"/api/products/{pid}").status_code, 404)
        self.assertEqual(client.put(f"/api/products/{pid}", json={"price": 1}).status_code, 404)

    def test_auto_register_from_ingest(self):
        body = self._ingest("智能净水器 W1 参数", "大通量 RO 膜，售价 1599 元，含三年滤芯。")
        product = body["entry"]["product"]
        self.assertEqual(product["name"], "智能净水器 W1")  # 尾部关键词已剥离
        self.assertEqual(product["price"], 1599.0)
        self.assertEqual(product["stock"], 100)  # 默认库存不显示缺货
        listed = [p["name"] for p in client.get("/api/products").json()]
        self.assertIn("智能净水器 W1", listed)

        again = self._ingest("智能净水器 W1 参数", "大通量 RO 膜，售价 1599 元，含三年滤芯。")
        names = [p["name"] for p in client.get("/api/products").json()]
        self.assertEqual(names.count("智能净水器 W1"), 1)  # 重复入库不新增
        self.assertEqual(again["entry"]["product"]["product_id"], product["product_id"])

    def test_no_register_for_non_product_doc(self):
        body = self._ingest("售后服务政策", "整机保修一年，7 天无理由退换。")
        self.assertIsNone(body["entry"]["product"])

    def test_auto_register_from_upload(self):
        files = {
            "file": (
                "智能空气炸锅K2参数.txt",
                "5.5L 大容量，价格 1299 元。".encode("utf-8"),
                "text/plain",
            )
        }
        resp = client.post("/api/knowledge/upload", files=files)
        self.assertEqual(resp.status_code, 200)
        product = resp.json()["entry"]["product"]
        self.assertEqual(product["name"], "智能空气炸锅K2")
        names = [p["name"] for p in client.get("/api/products").json()]
        self.assertIn("智能空气炸锅K2", names)


class TestContentTasks(unittest.TestCase):
    def test_generate_all_stages_with_progress(self):
        sid = client.post("/api/sessions").json()["session_id"]
        task = client.post(
            "/api/content/generate",
            json={"session_id": sid, "product_id": "P001", "name": "智能门锁 S1"},
        ).json()
        self.assertEqual(task["status"], "running")
        self.assertEqual(len(task["stages"]), 3)

        done = _wait_task(task["task_id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["error"], None)
        stages = {s["stage"]: s for s in done["stages"]}
        self.assertEqual(stages["topic"]["status"], "done")
        self.assertEqual(stages["copy"]["status"], "done")
        self.assertEqual(stages["script"]["status"], "done")
        for s in stages.values():
            self.assertTrue(s["content"])

    def test_task_list_and_unknown_task(self):
        listed = client.get("/api/content/tasks").json()
        self.assertIsInstance(listed, list)
        resp = client.get("/api/content/tasks/not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_resume_unknown_task_404(self):
        resp = client.post("/api/content/resume", json={"task_id": "not-exist"})
        self.assertEqual(resp.status_code, 404)

    def test_generate_carries_grounding_sources(self):
        """生成任务接地:任务记录携带 specs + 参考来源,片段不含提示词标记。"""
        sid = client.post("/api/sessions").json()["session_id"]
        ing = client.post(
            "/api/knowledge/ingest",
            json={
                "title": "智能门锁 S1 售后保修说明",  # 负向词标题,不触发商品登记
                "content": "智能门锁 S1 支持指纹、密码开锁，电池续航一年，保修两年。",
                "source": "内容任务测试",
            },
        ).json()
        doc_id = ing["entry"]["doc_id"]
        self.addCleanup(client.delete, f"/api/knowledge/{doc_id}")

        task = client.post(
            "/api/content/generate",
            json={"session_id": sid, "product_id": "P001", "name": "智能门锁 S1"},
        ).json()
        self.assertTrue(task["product"].get("specs"))  # start() 同步富化,running 即带参数
        done = _wait_task(task["task_id"])
        self.assertIsInstance(done.get("sources"), list)
        self.assertIn(doc_id, [s["doc_id"] for s in done["sources"]])
        self.assertTrue(all("用户问题" not in s["text"] for s in done["sources"]))
        self.assertTrue(all(s.get("text") for s in done["sources"]))


class TestPipeline(unittest.TestCase):
    def test_sample_pipeline(self):
        body = client.post("/api/pipeline/sample").json()
        report = body["report"]
        stats = report["stage_stats"]
        # 6 条输入：1 条空值被清洗、1 条重复被去重 → 输出 4 条
        self.assertEqual(stats["input"], 6)
        self.assertEqual(stats["clean_dropped"], 1)
        self.assertEqual(stats["dedupe_removed"], 1)
        self.assertEqual(stats["output"], 4)
        self.assertEqual(report["total_records"], 4)
        self.assertEqual(body["masked_total"], 4)
        self.assertGreaterEqual(report["mask_hits"].get("phone", 0), 1)
        self.assertTrue(report["samples"])

    def test_upload_json_file(self):
        payload = json.dumps(
            [{"content": "联系我 13812345678"}, {"content": "重复"}, {"content": "重复"}],
            ensure_ascii=False,
        ).encode("utf-8")
        resp = client.post(
            "/api/pipeline/upload",
            files={"file": ("records.json", payload, "application/json")},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["masked_total"], 2)  # 1 条重复被去重
        self.assertIn("138****5678", body["masked"][0]["content"])

    def test_upload_rejects_bad_suffix(self):
        resp = client.post(
            "/api/pipeline/upload",
            files={"file": ("evil.txt", b"whatever", "text/plain")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_run_with_records(self):
        resp = client.post(
            "/api/pipeline/run",
            json={"records": [{"content": "邮箱 test@example.com"}]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["report"]["mask_hits"].get("email", 0), 1)


if __name__ == "__main__":
    unittest.main()
