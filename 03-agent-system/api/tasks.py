"""内容生成后台任务管理。

``ContentAgent.generate`` 是分钟级同步调用且一次性返回全部阶段，
本模块用后台线程逐阶段串行执行（``generate(stage=X, task_id=T)``），
让前端可以轮询到真实进度；每阶段完成后合并写回 Checkpointer，
保持断点续跑语义与后端 ``resume`` 一致。
"""
from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

STAGE_ORDER = ["topic", "copy", "script"]
STAGE_LABELS = {"topic": "选题", "copy": "文案", "script": "话术脚本"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContentTaskManager:
    """内存任务注册表 + 后台执行线程（进程内单例，随 API 生命周期）。"""

    def __init__(self, system):
        self._system = system
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 对外动作
    # ------------------------------------------------------------------
    def start(self, session_id: str, product_info: dict, stage: str = "all") -> dict:
        """启动新任务：stage 为 all 或单个阶段，返回任务记录。"""
        task_id = str(uuid4())
        stages = list(STAGE_ORDER) if stage == "all" else [stage]
        # 一次性接地富化(商品参数 + 知识库检索片段):record / _spawn / 每阶段
        # generate / Checkpointer 状态全链路经 product_info 自动携带,每任务仅检索一次
        product_info = {**product_info, **self._system.build_grounding(product_info)}
        record = self._new_record(task_id, session_id, product_info, stages)
        with self._lock:
            self._tasks[task_id] = record
        self._spawn(task_id, session_id, product_info, stages)
        return self._copy(record)

    def resume(self, task_id: str, product_info: dict | None = None) -> dict:
        """断点续跑：从 Checkpointer 读取已完成阶段，仅补跑剩余阶段。"""
        state = self._system.content_agent.checkpointer.load(task_id)
        if not state:
            raise KeyError(f"未找到任务状态：{task_id}")
        session_id = state["session_id"]
        if product_info and "references" not in product_info:
            # 直接调用路径兜底:调用方传入裸 product_info 时补接地
            # (API 的 ResumeRequest 只传 task_id,通常走 checkpoint 里已富化的 product)
            product_info = {**product_info, **self._system.build_grounding(product_info)}
        product = product_info or state.get("product", {})
        done = {
            s
            for s, v in state.get("stages", {}).items()
            if v.get("status") == "done"
        }
        pending = [s for s in STAGE_ORDER if s not in done]
        if not pending:
            raise ValueError("该任务所有阶段均已完成，无需续跑")

        with self._lock:
            record = self._tasks.get(task_id) or self._new_record(
                task_id, session_id, product, list(STAGE_ORDER)
            )
            record.update(
                status="running",
                error=None,
                product=product,
                created_at=_now().isoformat(),
                finished_at=None,
                current=pending[0],
            )
            # 已完成阶段回填，剩余阶段标记 pending
            record["stages"] = [
                {
                    "stage": s,
                    "label": STAGE_LABELS[s],
                    "status": "done" if s in done else "pending",
                    "content": state.get("stages", {}).get(s, {}).get("content", ""),
                    "created_at": state.get("stages", {}).get(s, {}).get("created_at"),
                }
                for s in STAGE_ORDER
            ]
            self._tasks[task_id] = record
        self._spawn(task_id, session_id, product, pending)
        return self._copy(record)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return self._copy(record) if record else None

    def list(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            records = list(self._tasks.values())
        if session_id:
            records = [r for r in records if r["session_id"] == session_id]
        records.sort(key=lambda r: r["created_at"], reverse=True)
        return [self._copy(r) for r in records[:limit]]

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _new_record(
        self, task_id: str, session_id: str, product_info: dict, stages: list[str]
    ) -> dict:
        return {
            "task_id": task_id,
            "session_id": session_id,
            "product": product_info,
            "sources": list(product_info.get("references") or []),
            "status": "running",
            "stages": [
                {
                    "stage": s,
                    "label": STAGE_LABELS[s],
                    "status": "pending",
                    "content": "",
                    "created_at": None,
                }
                for s in STAGE_ORDER
                if s in stages or stages == STAGE_ORDER
            ],
            "current": stages[0] if stages else None,
            "error": None,
            "created_at": _now().isoformat(),
            "finished_at": None,
        }

    def _spawn(
        self, task_id: str, session_id: str, product_info: dict, stages: list[str]
    ) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(task_id, session_id, product_info, stages),
            daemon=True,
            name=f"content-{task_id[:8]}",
        )
        thread.start()

    def _run(
        self, task_id: str, session_id: str, product_info: dict, stages: list[str]
    ) -> None:
        agent = self._system.content_agent
        started = time.monotonic()
        try:
            for stage in stages:
                self._set_stage(task_id, stage, status="running", current=stage)
                results = agent.generate(
                    session_id, product_info, stage=stage, task_id=task_id
                )
                gc = results[0] if results else None
                if gc is None:
                    raise RuntimeError(f"阶段 {stage} 未返回结果")
                self._set_stage(
                    task_id,
                    stage,
                    status=gc.status.value,
                    content=gc.content,
                    created_at=gc.created_at.isoformat(),
                )
                # generate 只保存本次执行的阶段，这里合并写回全量状态，
                # 使 Checkpointer 与 resume 语义保持一致
                self._merge_checkpoint(task_id, session_id, product_info)
            self._finish(task_id, "done")
        except Exception as exc:  # noqa: BLE001 - 后台线程兜底，任何异常都记录
            self._finish(task_id, "failed", error=str(exc))
        finally:
            elapsed = round((time.monotonic() - started) * 1000)
            with self._lock:
                record = self._tasks.get(task_id)
                if record:
                    record["elapsed_ms"] = elapsed

    def _set_stage(
        self,
        task_id: str,
        stage: str,
        status: str,
        current: str | None = None,
        content: str | None = None,
        created_at: str | None = None,
    ) -> None:
        with self._lock:
            record = self._tasks[task_id]
            entry = next(s for s in record["stages"] if s["stage"] == stage)
            entry["status"] = status
            if content is not None:
                entry["content"] = content
            if created_at is not None:
                entry["created_at"] = created_at
            if current:
                record["current"] = current

    def _finish(self, task_id: str, status: str, error: str | None = None) -> None:
        with self._lock:
            record = self._tasks[task_id]
            record["status"] = status
            record["error"] = error
            record["finished_at"] = _now().isoformat()
            record["current"] = None

    def _merge_checkpoint(
        self, task_id: str, session_id: str, product_info: dict
    ) -> None:
        """把任务注册表里的全量阶段状态合并写回 Checkpointer。"""
        with self._lock:
            record = self._tasks[task_id]
            stages = {
                s["stage"]: {
                    "session_id": session_id,
                    "stage": s["stage"],
                    "content": s["content"],
                    "status": s["status"],
                    "task_id": task_id,
                    "created_at": s["created_at"] or _now().isoformat(),
                }
                for s in record["stages"]
                if s["status"] in ("done", "failed")
            }
        self._system.content_agent.checkpointer.save(
            task_id,
            {
                "session_id": session_id,
                "product": product_info,
                "task_id": task_id,
                "stages": stages,
            },
        )

    @staticmethod
    def _copy(record: dict) -> dict:
        return copy.deepcopy(record)
