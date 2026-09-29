"""运行全部单元测试（标准库 unittest，无需 pytest）。

用法：
    python run_tests.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 测试套件强制离线：即使 .env 配了真实 Key 也走 MockLLM，
# 保证测试确定性、零花费、不依赖网络（真实链路由 demo.py 验证）。
for _key in ("LLM_API_KEY", "LLM_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ[_key] = ""

# 知识库 / 商品目录状态全部指向临时目录 + 哈希向量 + simple 后端：
# 测试不下载 embedding 模型、不触网、不污染真实 data/ 下的持久化库。
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["RETRIEVAL_VECTOR_BACKEND"] = "simple"
_test_data = tempfile.mkdtemp(prefix="agent-system-tests-")
os.environ["RETRIEVAL_FTS_DB"] = os.path.join(_test_data, "fts.db")
os.environ["RETRIEVAL_DOCS_DB"] = os.path.join(_test_data, "docs.db")
os.environ["RETRIEVAL_CHROMA_PATH"] = os.path.join(_test_data, "chroma")
os.environ["PRODUCTS_DB"] = os.path.join(_test_data, "products.db")

if __name__ == "__main__":
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir="tests", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
