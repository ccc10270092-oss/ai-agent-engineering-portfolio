"""向量检索（BR-02.2 / G-2）。

embedding 三种模式（``embedding_backend`` 配置）：
- ``local``：本地 ONNX 模型（fastembed，默认 BAAI/bge-small-zh-v1.5），
  中文语义召回好；首次运行自动下载约 100MB 到 ``data/models/``；
- ``api``：OpenAI 兼容 ``/embeddings`` 接口（需 model + Key + Base URL）；
- ``hash``：内置特征哈希词袋向量 + 余弦相似度，零依赖、确定性、可离线；
- 空 = 自动：三项齐 → api，否则 hash。

任一模式加载失败（未装 fastembed / 下载失败 / Key 失效）自动回退哈希向量，
系统始终可用（与「无 Key 亦可跑通」的项目原则一致）。

后端默认 ``chroma``（持久化，未安装 chromadb 自动回退 ``simple``）；
两者共享同一套 embedding 生成逻辑，接口一致，可无缝切换。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path

from app_core.config import PROJECT_ROOT
from app_core.logger import get_logger
from app_core.models import Chunk

log = get_logger("retrieval.vector")

_EMBED_DIM = 256
_DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"


def _grams(text: str, n: int):
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _hash_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """特征哈希词袋向量（L2 归一化），离线兜底用。"""
    vec = [0.0] * dim
    tokens = re.findall(r"[A-Za-z0-9_]+|[一-鿿]", (text or "").lower())
    for tok in tokens:
        for gram in _grams(tok, 1) | _grams(tok, 2) | _grams(tok, 3):
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)  # noqa: S324
            idx = h % dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# embedder：统一为可内省的 callable（mode / model_name / dim / fallback），
# /api/health 直接读这些属性展示当前向量模式，无需重复决策逻辑。
# ---------------------------------------------------------------------------


class _HashEmbedding:
    """特征哈希词袋向量（离线兜底）。"""

    mode = "hash"
    model_name = "特征哈希(256维)"
    dim = _EMBED_DIM
    fallback = False

    def __call__(self, text: str) -> list[float]:
        return _hash_embed(text)


class _OpenAIEmbedding:
    """OpenAI 兼容 embedding 客户端（仅标准库 urllib）。"""

    mode = "api"
    fallback = False

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.model_name = model
        self.dim = None  # 由服务端模型决定，首调前未知
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") + "/embeddings"

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": [text]}
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 用户自配地址
            data = json.loads(resp.read().decode("utf-8"))
        return data["data"][0]["embedding"]

    __call__ = embed


class _LocalEmbedding:
    """本地 ONNX embedding（fastembed），急切加载。

    构造时即加载模型（首次运行自动下载），避免首个检索请求阻塞在
    100MB 下载上打爆前端超时；任何失败永久降级为特征哈希并向
    /api/health 暴露 fallback=True。
    """

    mode = "local"

    def __init__(self, model_name: str = _DEFAULT_LOCAL_MODEL, cache_dir: str = "data/models"):
        self.model_name = model_name or _DEFAULT_LOCAL_MODEL
        self.fallback = False
        self.dim = None
        cache = Path(cache_dir)
        if not cache.is_absolute():
            cache = PROJECT_ROOT / cache
        try:
            from fastembed import TextEmbedding  # type: ignore

            log.info(
                "加载本地 embedding 模型 %s（首次运行会先下载约 100MB 到 %s）…",
                self.model_name,
                cache,
            )
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(cache),
                providers=["CPUExecutionProvider"],
            )
            self.dim = len(self._embed_one("维度探测"))
            log.info("本地 embedding 模型就绪（%d 维）", self.dim)
        except Exception as exc:  # noqa: BLE001 - 任何加载/下载失败都降级保可用
            self._model = None
            self.fallback = True
            self.dim = _EMBED_DIM
            log.warning(
                "本地 embedding 模型加载失败（%s），回退为特征哈希向量；"
                "国内网络可在 .env 设置 HF_ENDPOINT=https://hf-mirror.com 后重试",
                exc,
            )

    def _embed_one(self, text: str) -> list[float]:
        return list(self._model.embed([text]))[0].tolist()

    def __call__(self, text: str) -> list[float]:
        if self._model is None:
            return _hash_embed(text)
        return self._embed_one(text)


def _make_embedder(config):
    """按配置返回 ``text -> list[float]`` 的 embedding 函数（可内省 mode 等属性）。"""
    backend = (getattr(config, "embedding_backend", "") or "").strip().lower()
    has_api_fields = bool(
        getattr(config, "embedding_model", "")
        and getattr(config, "embedding_api_key", "")
        and getattr(config, "embedding_base_url", "")
    )

    if backend == "hash":
        return _HashEmbedding()
    if backend == "local":
        return _LocalEmbedding(
            model_name=getattr(config, "embedding_model", "") or _DEFAULT_LOCAL_MODEL
        )
    if has_api_fields:  # 显式 api 或自动模式且三项齐
        client = _OpenAIEmbedding(
            config.embedding_model, config.embedding_api_key, config.embedding_base_url
        )
        log.info("使用 API embedding 模型：%s", config.embedding_model)
        return client
    if backend == "api":
        log.warning("embedding_backend=api 但 embedding 三项配置不全，回退为特征哈希向量")
    return _HashEmbedding()


def embedding_info(embed) -> dict:
    """供 /api/health 展示的 embedding 概要。"""
    return {
        "mode": getattr(embed, "mode", "hash"),
        "model": getattr(embed, "model_name", "特征哈希(256维)"),
        "dim": getattr(embed, "dim", None),
        "fallback": bool(getattr(embed, "fallback", False)),
    }


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class VectorStore:
    """向量存储接口。"""

    def add(self, chunk: Chunk) -> None:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError

    def remove(self, doc_id: str) -> None:
        """删除指定文档的全部向量。"""
        raise NotImplementedError

    def clear(self) -> None:
        """清空全部向量。"""
        raise NotImplementedError


class SimpleVectorStore(VectorStore):
    """内存向量存储（零依赖）。"""

    def __init__(self, embed=None):
        self._embed = embed or _hash_embed
        self._meta: dict = {}
        self._vecs: list = []
        self._ids: list = []

    def add(self, chunk: Chunk) -> None:
        vec = self._embed(chunk.text)
        self._meta[chunk.chunk_id] = (chunk.doc_id, chunk.text)
        self._vecs.append(vec)
        self._ids.append(chunk.chunk_id)

    def remove(self, doc_id: str) -> None:
        keep_ids = [cid for cid in self._ids if self._meta[cid][0] != doc_id]
        keep = set(keep_ids)
        self._vecs = [v for v, cid in zip(self._vecs, self._ids) if cid in keep]
        self._ids = keep_ids
        for cid in [c for c, m in self._meta.items() if m[0] == doc_id]:
            del self._meta[cid]

    def clear(self) -> None:
        self._meta.clear()
        self._vecs.clear()
        self._ids.clear()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._vecs:
            return []
        q = self._embed(query)
        pairs = [(_cosine(q, self._vecs[i]), self._ids[i]) for i in range(len(self._vecs))]
        scored = sorted(pairs, key=lambda x: -x[0])[: max(top_k * 2, 1)]
        return [
            {
                "chunk_id": cid,
                "doc_id": self._meta[cid][0],
                "text": self._meta[cid][1],
                "vector_score": max(score, 0.0),
            }
            for score, cid in scored
        ]


class ChromaVectorStore(VectorStore):
    """ChromaDB 持久化后端，接口与 SimpleVectorStore 一致。

    不使用 chromadb 的 EmbeddingFunction 机制（1.x 版本对自定义实现有
    name/config 协议要求），改为 add/query 时显式传 embeddings——
    embedding 统一由本类持有的 ``_embed`` 生成，与后端版本解耦。

    维度守卫：切换 embedding 模型（如 哈希 256 维 → 本地 bge 512 维）后，
    旧向量对新 embedder 物理不可用（chromadb 首次 add/query 即抛异常），
    故启动时检测维度不匹配即重置向量库，并提示重新入库。
    """

    def __init__(self, path: str = "./data/chroma", embed=None):
        import chromadb  # type: ignore

        self._embed = embed or _hash_embed
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(name="knowledge")
        self._guard_dimension()

    def _guard_dimension(self) -> None:
        if self._collection.count() == 0:
            return
        try:
            stored = self._collection.get(limit=1, include=["embeddings"])
            vecs = stored.get("embeddings")
            if vecs is None or len(vecs) == 0:
                return
            stored_dim = len(vecs[0])
            # 探测当前 embedder 维度（api 模式为一次网络调用，失败则跳过守卫）
            current_dim = len(self._embed("__dimension_probe__"))
        except Exception:  # noqa: BLE001 - 取样/探测失败不阻断启动
            return
        if stored_dim != current_dim:
            log.warning(
                "检测到向量维度变化（库内 %d 维 != 当前 %d 维），已重置向量库——"
                "旧向量已不可用，请重新入库文档（FTS 全文索引与文档登记不受影响）",
                stored_dim,
                current_dim,
            )
            self._client.delete_collection("knowledge")
            self._collection = self._client.get_or_create_collection(name="knowledge")

    def add(self, chunk: Chunk) -> None:
        # upsert：相同内容 id 原地覆盖，重复入库不累积副本
        self._collection.upsert(
            ids=[chunk.chunk_id],
            documents=[chunk.text],
            metadatas=[{"doc_id": chunk.doc_id, "chunk_id": chunk.chunk_id}],
            embeddings=[self._embed(chunk.text)],
        )

    def remove(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": doc_id})

    def clear(self) -> None:
        self._client.delete_collection("knowledge")
        self._collection = self._client.get_or_create_collection(name="knowledge")

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        res = self._collection.query(
            query_embeddings=[self._embed(query)], n_results=max(top_k * 2, 1)
        )
        out = []
        ids = res["ids"][0]
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res.get("distances", [[]])[0]
        for i, cid in enumerate(ids):
            meta = metas[i] or {}
            dist = dists[i] if i < len(dists) else 0.0
            score = 1.0 / (1.0 + float(dist)) if dist is not None else 0.0
            out.append({
                "chunk_id": cid,
                "doc_id": meta.get("doc_id", ""),
                "text": docs[i],
                "vector_score": score,
            })
        return out


def get_vector_store(config) -> VectorStore:
    """按配置返回向量后端（默认 chroma，未安装则回退 simple）。"""
    backend = getattr(config, "vector_backend", "chroma")
    embed = _make_embedder(config)
    store: VectorStore | None = None
    if backend == "chroma":
        try:
            path = getattr(config, "chroma_path", "") or "./data/chroma"
            log.info("使用 ChromaDB 向量后端（%s）", path)
            store = ChromaVectorStore(path=path, embed=embed)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChromaDB 不可用（%s），回退为 simple 后端", exc)
    if store is None:
        store = SimpleVectorStore(embed=embed)
    store.embedding_info = embedding_info(embed)
    return store
