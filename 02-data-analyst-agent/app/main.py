from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import analyze
from app.config import settings
from app.database import get_schema, initialize_database


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="澄析 · 数据分析 Agent",
    description="通过安全 SQL 工具分析演示电商数据的自然语言 Agent。",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1500)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="需要有效的管理员令牌。")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def public_config() -> dict[str, Any]:
    llm_ready = bool(settings.api_key and settings.model != "your-openai-compatible-model")
    return {"demo_mode": not llm_ready, "model": settings.model if llm_ready else None}


@app.get("/api/schema")
async def schema() -> dict[str, Any]:
    return {"tables": get_schema()}


@app.post("/api/analyze")
async def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="分析问题不能为空。")
    try:
        return analyze(request.question.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent 分析失败：{str(exc)[:300]}") from exc


@app.get("/api/admin/data-summary", dependencies=[Depends(require_admin)])
async def data_summary() -> dict[str, Any]:
    from app.sql_safety import execute_readonly

    return {
        "tables": get_schema(),
        "row_counts": {
            table: execute_readonly(f"SELECT COUNT(*) AS row_count FROM {table}").rows[0]["row_count"]
            for table in get_schema()
        },
    }
