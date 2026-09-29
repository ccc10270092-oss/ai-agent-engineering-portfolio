"""模块 C：混合检索（SQLite-FTS5 全文 + ChromaDB/简单向量，加权融合）。"""
from .chunker import chunk_text, chunk_doc
from .docstore import DocRegistry
from .file_loader import SUPPORTED_SUFFIXES, extract_text
from .fts import FTSIndex
from .vector import VectorStore, embedding_info, get_vector_store
from .hybrid import HybridRetriever

__all__ = [
    "chunk_text",
    "chunk_doc",
    "DocRegistry",
    "SUPPORTED_SUFFIXES",
    "extract_text",
    "FTSIndex",
    "VectorStore",
    "embedding_info",
    "get_vector_store",
    "HybridRetriever",
]