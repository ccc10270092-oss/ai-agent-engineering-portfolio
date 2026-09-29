"""FastAPI 网关：把 ``service.System`` 门面暴露为 REST API，并托管 Vue 前端。

开发模式（前端 5173 / 后端 8000，Vite 代理 /api）：
    python -m uvicorn api.main:app --reload --port 8000
生产模式（同一端口提供页面与接口）：
    python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

注意：System 及其会话 / FTS 索引均为进程内状态，务必单 worker 部署。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.schemas import (
    AskRequest,
    CreateSessionRequest,
    GenerateRequest,
    IngestRequest,
    PipelineRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
    ResumeRequest,
    SearchRequest,
    to_jsonable,
)
from api.tasks import ContentTaskManager
from data_pipeline.loader import load_records
from demo import sample_knowledge, sample_records
from retrieval.file_loader import SUPPORTED_SUFFIXES, extract_text
from service import get_system

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="智能 AI Agent 售前服务系统 API", version="1.0.0")

# 开发模式下 Vue dev server 跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 进程内共享状态：System 单例 + 内容任务管理器
# （知识库状态——FTS / 向量 / 文档登记——均在 System 内持久化，重启不丢）
sys_ = get_system()
tasks = ContentTaskManager(sys_)


@app.get("/api/health")
def health():
    """系统健康与运行模式（离线 Mock / 真实模型、向量模式）。"""
    llm = sys_.config.llm
    ret = sys_.config.retrieval
    return {
        "status": "ok",
        "llm_mode": "real" if llm.api_key and llm.base_url else "mock",
        "llm_model": llm.model,
        "embedding": getattr(sys_.vector, "embedding_info", None)
        or {"mode": "hash", "model": "特征哈希(256维)", "dim": 256, "fallback": False},
        "retrieval": {
            "top_k": ret.top_k,
            "fts_weight": ret.fts_weight,
            "vector_weight": ret.vector_weight,
            "chunk_size": ret.chunk_size,
        },
    }


@app.get("/api/stats")
def stats():
    """总览页统计：知识库、会话、消息、生成任务。"""
    sessions = sys_.list_sessions()
    messages = sum(len(sys_.session_history(s.session_id)) for s in sessions)
    task_list = tasks.list(limit=200)
    total_docs, total_chunks = sys_.docs.totals()
    return {
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "total_products": sys_.products.count(),
        "total_sessions": len(sessions),
        "total_messages": messages,
        "total_tasks": len(task_list),
        "tasks_done": sum(1 for t in task_list if t["status"] == "done"),
        "tasks_running": sum(1 for t in task_list if t["status"] == "running"),
    }


# ---------------------------------------------------------------------------
# 会话（模块 A / G-4 隔离）
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
def list_sessions():
    return to_jsonable(sys_.list_sessions())


@app.post("/api/sessions")
def create_session(req: CreateSessionRequest | None = None):
    """新建会话；body 可省略（等价 user_id=""）。"""
    session = sys_.create_session(req.user_id if req else "")
    return to_jsonable(session)


@app.get("/api/sessions/{session_id}/history")
def session_history(session_id: str):
    return to_jsonable(sys_.session_history(session_id))


# ---------------------------------------------------------------------------
# 知识入库与检索（模块 C / FR-02）：文档登记 SQLite 持久化，重启不丢
# ---------------------------------------------------------------------------

@app.get("/api/knowledge")
def knowledge_list():
    """已入库文档登记表（SQLite 持久化，重启不丢）。"""
    docs = sys_.list_docs()
    return {
        "docs": docs,
        "total_docs": len(docs),
        "total_chunks": sum(d["chunks"] for d in docs),
    }


@app.post("/api/knowledge/ingest")
def ingest(req: IngestRequest):
    entry = sys_.ingest_doc(req.title, req.content, req.source)
    return {"entry": entry, "chunks": entry["chunks"]}


@app.post("/api/knowledge/sample")
def ingest_sample():
    """一键载入演示知识库（4 篇产品 / 售后文档；重复点击幂等不累积）。"""
    entries = [
        sys_.ingest_doc(title, content, "示例知识库")
        for title, content in sample_knowledge()
    ]
    total_docs, total_chunks = sys_.docs.totals()
    return {
        "entries": entries,
        "total_docs": total_docs,
        "total_chunks": total_chunks,
    }


@app.delete("/api/knowledge/{doc_id}")
def knowledge_delete(doc_id: str):
    """删除指定文档（FTS / 向量 / 登记三路同删）。"""
    entry = sys_.delete_doc(doc_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"deleted": entry}


@app.post("/api/knowledge/clear")
def knowledge_clear():
    """清空知识库（FTS / 向量 / 登记三路全清）。"""
    return sys_.clear_knowledge()


@app.post("/api/knowledge/upload")
async def knowledge_upload(file: UploadFile = File(...)):
    """上传知识文档（.txt/.md/.csv/.pdf/.docx）提取文本并入库。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {' / '.join(sorted(SUPPORTED_SUFFIXES))} 文件",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（上限 10MB）")
    try:
        text = extract_text(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(text) > 1_000_000:
        raise HTTPException(status_code=400, detail="提取文本过长（上限 100 万字）")
    entry = sys_.ingest_doc(
        title=Path(file.filename or "未命名文档").stem,
        content=text,
        source=f"文件上传：{file.filename}",
    )
    return {"entry": entry, "chunks": entry["chunks"]}


@app.post("/api/knowledge/search")
def search(req: SearchRequest):
    return to_jsonable(sys_.search(req.query, req.top_k))


# ---------------------------------------------------------------------------
# 智能问答（模块 D / FR-04）
# ---------------------------------------------------------------------------

@app.post("/api/ask")
def ask(req: AskRequest):
    """售前咨询（ReAct）。真实模型下单次推理最长约 2 分钟。"""
    answer = sys_.ask(req.session_id, req.query)
    return to_jsonable(answer)


# ---------------------------------------------------------------------------
# 商品目录（供内容生成 / 咨询展示；持久化 + 管理接口）
# ---------------------------------------------------------------------------

@app.get("/api/products")
def products():
    return sys_.list_products()


@app.post("/api/products")
def create_product(req: ProductCreateRequest):
    """手动新增商品；同名返回 400。"""
    try:
        return sys_.add_product(req.name, req.specs, req.category, req.price, req.stock)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/products/{product_id}")
def update_product(product_id: str, req: ProductUpdateRequest):
    """编辑商品（转为手动管理，不再被文档登记覆盖）；改名撞名返回 400。"""
    fields = req.model_dump(exclude_none=True)
    try:
        entry = sys_.update_product(product_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail=f"商品不存在：{product_id}")
    return entry


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str):
    """删除商品；关联的知识文档不受影响。"""
    entry = sys_.delete_product(product_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"商品不存在：{product_id}")
    return {"deleted": entry}


# ---------------------------------------------------------------------------
# 内容生成（模块 E / FR-05）——后台任务 + 轮询
# ---------------------------------------------------------------------------

@app.post("/api/content/generate")
def content_generate(req: GenerateRequest):
    product_info = {
        "product_id": req.product_id,
        "name": req.name or req.product_id,
    }
    record = tasks.start(req.session_id, product_info, req.stage)
    return record


@app.post("/api/content/resume")
def content_resume(req: ResumeRequest):
    try:
        return tasks.resume(req.task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/content/tasks")
def content_tasks(session_id: str | None = None):
    return tasks.list(session_id=session_id)


@app.get("/api/content/tasks/{task_id}")
def content_task(task_id: str):
    record = tasks.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return record


# ---------------------------------------------------------------------------
# 数据管道（模块 B / FR-03、G-3）
# ---------------------------------------------------------------------------

def _run_pipeline(records: list[dict]) -> dict:
    masked, report = sys_.process_data(records)
    return {
        "masked": masked[:1000],
        "masked_total": len(masked),
        "report": to_jsonable(report),
    }


@app.post("/api/pipeline/run")
def pipeline_run(req: PipelineRequest):
    return _run_pipeline(req.records)


@app.post("/api/pipeline/sample")
def pipeline_sample():
    """运行内置示例管道（含 PII / 重复 / 空值的 6 条客服记录）。"""
    return _run_pipeline(sample_records())


@app.post("/api/pipeline/upload")
async def pipeline_upload(file: UploadFile = File(...)):
    """上传 CSV / JSON / JSONL 原始客服数据并跑完整个管道。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl"}:
        raise HTTPException(status_code=400, detail="仅支持 .csv / .json / .jsonl 文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（上限 5MB）")

    with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        records = load_records(path)
    except Exception as exc:  # noqa: BLE001 - 解析错误统一反馈给前端
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}") from exc
    finally:
        Path(path).unlink(missing_ok=True)

    if not records:
        raise HTTPException(status_code=400, detail="文件中没有可识别的记录")
    if len(records) > 5000:
        raise HTTPException(status_code=400, detail="记录数超过上限（5000 条）")
    return _run_pipeline(records)


# ---------------------------------------------------------------------------
# 生产模式：托管 Vue 构建产物（frontend/dist）
# ---------------------------------------------------------------------------

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """静态资源直出；其余路径回退到 index.html（SPA 前端路由）。"""
        target = _DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_DIST / "index.html")
