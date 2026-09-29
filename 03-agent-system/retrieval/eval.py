"""检索质量评测（G-2 / AC-02.1 / AC-02.2 / AC-07.3）。

在同一语料上分别跑「FTS5 单词引擎」「向量单词引擎」「混合融合」三种检索，
按 hit@k 计算命中率，输出对比报告，作为 G-2 命中率 ≥85% 与「融合优于单引擎」
的量化证据。

说明：评测固定使用 SimpleVectorStore（内置哈希向量）以保证可离线、确定性复现；
配置真实 embedding 模型后向量路召回会更强，命中率只升不降。
"""
from __future__ import annotations

import json
from pathlib import Path

from app_core.models import KnowledgeDoc
from .chunker import chunk_doc
from .fts import FTSIndex
from .hybrid import HybridRetriever
from .vector import SimpleVectorStore

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "eval_qa.json"


def load_eval_data(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DATA_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def _doc_id(r) -> str:
    return r["doc_id"] if isinstance(r, dict) else r.doc_id


def _hit(result, expected_doc_id: str, k: int) -> bool:
    return any(_doc_id(r) == expected_doc_id for r in result[:k])


def run_eval(
    data: dict | None = None,
    top_k: int = 5,
    fts_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> dict:
    """运行评测，返回三引擎命中率对比报告。"""
    data = data or load_eval_data()

    # 三套引擎共用同一份语料，独立打分
    fts = FTSIndex(":memory:")
    vector = SimpleVectorStore()
    hybrid = HybridRetriever(
        fts, vector, chunk_size=512, overlap=0, top_k=top_k,
        fts_weight=fts_weight, vector_weight=vector_weight,
    )

    title_to_id: dict[str, str] = {}
    for i, doc in enumerate(data["knowledge"]):
        doc_id = f"doc_{i}"
        title_to_id[doc["title"]] = doc_id
        kd = KnowledgeDoc(title=doc["title"], content=doc["content"], doc_id=doc_id)
        for chunk in chunk_doc(kd, 512, 0):
            fts.add(chunk)
            vector.add(chunk)

    n = 0
    fts_hits = vector_hits = hybrid_hits = 0
    details = []
    for qa in data["queries"]:
        expected_id = title_to_id.get(qa["expected"])
        if expected_id is None:
            continue
        n += 1
        fts_ok = _hit(fts.search(qa["query"], top_k), expected_id, top_k)
        vec_ok = _hit(vector.search(qa["query"], top_k), expected_id, top_k)
        hyb_ok = _hit(hybrid.search(qa["query"], top_k), expected_id, top_k)
        fts_hits += int(fts_ok)
        vector_hits += int(vec_ok)
        hybrid_hits += int(hyb_ok)
        details.append({
            "query": qa["query"],
            "expected": qa["expected"],
            "fts": fts_ok,
            "vector": vec_ok,
            "hybrid": hyb_ok,
        })

    report = {
        "total": n,
        "top_k": top_k,
        "fts": {"hits": fts_hits, "rate": round(fts_hits / n, 4) if n else 0.0},
        "vector": {"hits": vector_hits, "rate": round(vector_hits / n, 4) if n else 0.0},
        "hybrid": {"hits": hybrid_hits, "rate": round(hybrid_hits / n, 4) if n else 0.0},
        "details": details,
    }
    return report


def print_report(report: dict) -> None:
    for engine in ("fts", "vector", "hybrid"):
        r = report[engine]
        print(f"{engine:7s} 命中 {r['hits']}/{report['total']}  命中率 {r['rate']*100:.1f}%")
    print("\n逐条明细（fts / vector / hybrid 是否命中）：")
    for d in report["details"]:
        mark = lambda b: "✓" if b else "✗"  # noqa: E731
        print(f"  {mark(d['fts'])} {mark(d['vector'])} {mark(d['hybrid'])}  {d['query']}  ->  {d['expected']}")


if __name__ == "__main__":
    print_report(run_eval())