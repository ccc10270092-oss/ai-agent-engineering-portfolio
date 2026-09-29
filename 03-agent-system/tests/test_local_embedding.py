"""embedding 模式决策测试（全离线，不下载模型、不触网）。

覆盖 _make_embedder 的四种 backend 分支与 local 加载失败的哈希降级。
"""
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from retrieval.vector import _make_embedder, embedding_info


def _config(backend="", model="", key="", base=""):
    return SimpleNamespace(
        embedding_backend=backend,
        embedding_model=model,
        embedding_api_key=key,
        embedding_base_url=base,
    )


class TestMakeEmbedder(unittest.TestCase):
    def test_explicit_hash(self):
        embed = _make_embedder(_config(backend="hash", model="x", key="y", base="z"))
        self.assertEqual(embed.mode, "hash")
        v1, v2 = embed("测试"), embed("测试")
        self.assertEqual(len(v1), 256)
        self.assertEqual(v1, v2)  # 确定性

    def test_auto_with_api_fields(self):
        embed = _make_embedder(_config(model="doubao-embedding", key="k", base="https://x"))
        self.assertEqual(embed.mode, "api")
        self.assertEqual(embed.model_name, "doubao-embedding")

    def test_auto_without_api_fields_falls_back_to_hash(self):
        embed = _make_embedder(_config())
        self.assertEqual(embed.mode, "hash")

    def test_explicit_api_with_incomplete_fields_falls_back(self):
        embed = _make_embedder(_config(backend="api", model="m", key="", base=""))
        self.assertEqual(embed.mode, "hash")

    def test_local_backend_with_import_failure_degrades_to_hash(self):
        # fastembed 视为不可导入（未安装 / 损坏），必须降级而不是抛异常
        with mock.patch.dict(sys.modules, {"fastembed": None}):
            embed = _make_embedder(_config(backend="local"))
        self.assertEqual(embed.mode, "local")
        self.assertTrue(embed.fallback)
        self.assertEqual(len(embed("测试")), 256)  # 哈希兜底
        info = embedding_info(embed)
        self.assertEqual(info["mode"], "local")
        self.assertTrue(info["fallback"])


class TestEmbeddingInfo(unittest.TestCase):
    def test_plain_function_defaults(self):
        # embedder 是裸函数（如 SimpleVectorStore 默认 _hash_embed）时的兜底
        info = embedding_info(lambda text: [0.0] * 256)
        self.assertEqual(info, {
            "mode": "hash", "model": "特征哈希(256维)", "dim": None, "fallback": False,
        })


if __name__ == "__main__":
    unittest.main()
