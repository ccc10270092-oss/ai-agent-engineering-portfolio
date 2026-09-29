"""内容生成 Agent（LangGraph 多阶段工作流，FR-05 / BR-05.x）。

以 LangGraph ``StateGraph`` 编排三阶段「选题 → 文案 → 脚本」：
    START → gen_topic → gen_copy → gen_script → END
    任一阶段失败 → safe_call retry(≤3) → 仍失败 → skip_node（产出 FAILED 片段）→ 继续
    Checkpointer 记录各阶段状态，支持中断后 resume 续跑剩余阶段。

对外接口保持 ``ContentAgent.generate / resume`` 不变，``service.py`` /
``demo.py`` / 前端 / 测试均无需改动。图编译时挂载 LangGraph ``InMemorySaver``
（LangGraph Checkpointer），跨进程持久化恢复复用 ``persist.Checkpointer``（JSON，
因未安装 langgraph-checkpoint-sqlite）。
"""
from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app_core.llm import LLMClient
from app_core.logger import get_logger
from app_core.models import ContentStage, ContentStatus, GeneratedContent
from app_core.safe_call import DegradedResult, safe_call

from .persist import Checkpointer
from .stages import STAGE_GENERATORS

log = get_logger("agents.content")

_ALL_STAGES = [ContentStage.TOPIC, ContentStage.COPY, ContentStage.SCRIPT]


def _gc_to_dict(gc: GeneratedContent) -> dict:
    """GeneratedContent → JSON 安全字典（供 LangGraph Checkpointer 序列化）。"""
    return {
        "session_id": gc.session_id,
        "stage": gc.stage.value,
        "content": gc.content,
        "status": gc.status.value,
        "task_id": gc.task_id,
        "created_at": gc.created_at.isoformat(),
    }


def _dict_to_gc(d: dict) -> GeneratedContent:
    return GeneratedContent(
        session_id=d["session_id"],
        stage=ContentStage(d["stage"]),
        content=d["content"],
        status=ContentStatus(d["status"]),
        task_id=d.get("task_id") or str(uuid4()),
        created_at=datetime.fromisoformat(d["created_at"]),
    )


class ContentState(TypedDict, total=False):
    """内容生成状态：仅在 ``results`` 中累积 JSON 安全的结果片段。"""

    results: list


class ContentAgent:
    """内容生成 Agent（LangGraph StateGraph 编排）。"""

    def __init__(
        self,
        llm: LLMClient,
        retries: int = 3,
        checkpointer: Checkpointer | None = None,
    ):
        self.llm = llm
        self.retries = retries
        self.checkpointer = checkpointer or Checkpointer()

    def generate(
        self,
        session_id: str,
        product_info: dict,
        stage: str = "all",
        task_id: str | None = None,
    ) -> list[GeneratedContent]:
        """执行内容生成。stage 为 "all" 或 topic/copy/script 之一。"""
        task_id = task_id or str(uuid4())
        targets = _ALL_STAGES if stage == "all" else [_to_stage(stage)]
        results = self._run_stages(targets, session_id, product_info, task_id)

        # 持久化到 JSON Checkpointer，支持跨进程 resume
        state = {
            "session_id": session_id,
            "product": product_info,
            "task_id": task_id,
            "stages": {gc.stage.value: _gc_to_dict(gc) for gc in results},
        }
        self.checkpointer.save(task_id, state)
        return results

    def resume(self, task_id: str, product_info: dict) -> list[GeneratedContent]:
        """断点恢复：从 Checkpointer 读取已完成阶段，续跑剩余阶段。"""
        state = self.checkpointer.load(task_id)
        if not state:
            raise ValueError(f"未找到任务状态：{task_id}")
        done = {
            s
            for s, v in state.get("stages", {}).items()
            if v.get("status") == ContentStatus.DONE.value
        }
        pending = [s for s in _ALL_STAGES if s.value not in done]
        results = self._run_stages(
            pending, state["session_id"], state.get("product", product_info), task_id
        )
        # 回写检查点：新完成的阶段持久化，否则再次 resume 会重跑这些阶段
        state.setdefault("stages", {}).update(
            {gc.stage.value: _gc_to_dict(gc) for gc in results}
        )
        self.checkpointer.save(task_id, state)
        return results

    # ------------------------------------------------------------------
    # LangGraph 编排
    # ------------------------------------------------------------------
    def _run_stages(
        self,
        stages: list[ContentStage],
        session_id: str,
        product_info: dict,
        task_id: str,
    ) -> list[GeneratedContent]:
        g = StateGraph(ContentState)
        prev = START
        for s in stages:
            name = f"gen_{s.value}"
            g.add_node(name, self._stage_node(session_id, product_info, s, task_id))
            g.add_edge(prev, name)
            prev = name
        g.add_edge(prev, END)
        app = g.compile(checkpointer=InMemorySaver())
        state = app.invoke(
            {"results": []},
            {"configurable": {"thread_id": task_id}},
        )
        return [_dict_to_gc(r) for r in state.get("results", [])]

    def _stage_node(self, session_id: str, product_info: dict, stage: ContentStage, task_id: str):
        def node(state: dict) -> dict:
            gc = self._run_stage(session_id, product_info, stage, task_id)
            results = list(state.get("results", []))
            results.append(_gc_to_dict(gc))
            return {"results": results}

        return node

    # ------------------------------------------------------------------
    # 单阶段执行（safe_call 重试 + 失败跳过）
    # ------------------------------------------------------------------
    def _run_stage(
        self, session_id: str, product_info: dict, stage: ContentStage, task_id: str
    ) -> GeneratedContent:
        gen = STAGE_GENERATORS[stage]
        result = safe_call(
            gen, self.llm, product_info, retries=self.retries, delay=0.0, degraded_value=""
        )
        if isinstance(result, DegradedResult):
            log.warning("阶段 %s 重试耗尽，跳过该节点", stage.value)
            return GeneratedContent(
                session_id=session_id,
                stage=stage,
                content="",
                status=ContentStatus.FAILED,
                task_id=task_id,
            )
        return GeneratedContent(
            session_id=session_id,
            stage=stage,
            content=result,
            status=ContentStatus.DONE,
            task_id=task_id,
        )


def _to_stage(stage: str) -> ContentStage:
    try:
        return ContentStage(stage)
    except ValueError as exc:
        raise ValueError(f"未知阶段：{stage}，可选 topic/copy/script/all") from exc