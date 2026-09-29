"""售前咨询 Agent（LangGraph ReAct 状态机，FR-04 / BR-04.x）。

以 LangGraph ``StateGraph`` 实现 ReAct 自主决策循环，状态流转：
    START → think →(有动作)→ act ─(未超步)─→ think ... → respond → END
                  └(无动作)──────────────────→ respond
    act 工具失败（retry ≤2 仍失败）→ degrade → END
    超 max_steps → degrade → END

对外接口保持 ``ReActAgent.run(session_id, user_query) -> AgentAnswer`` 不变，
``service.py`` / ``demo.py`` / 前端 / 测试均无需改动。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app_core.llm import LLMClient
from app_core.logger import get_logger
from app_core.safe_call import DegradedResult
from .retry import call_tool
from .tools import ToolAction, ToolRouter, Tools

log = get_logger("agents.pre_sale")


@dataclass
class AgentAnswer:
    """售前咨询结果。"""

    answer: str
    source_chunks: list = field(default_factory=list)
    trace: list = field(default_factory=list)      # 每步 {step, stage, tool}
    degraded: bool = False
    reason: str = ""


class ReActState(TypedDict, total=False):
    """ReAct 状态（LangGraph 按键合并，节点返回部分更新即可）。"""

    session_id: str
    user_query: str
    context: str
    history: list
    step: int
    pending_action: dict | None
    observations: list
    source_chunks: list
    trace: list
    degraded: bool
    reason: str
    answer: str


class ReActAgent:
    """ReAct 售前咨询 Agent（LangGraph StateGraph 编排）。"""

    def __init__(
        self,
        llm: LLMClient,
        tools: Tools,
        max_steps: int = 10,
        tool_retries: int = 2,
        router: ToolRouter | None = None,
    ):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.tool_retries = tool_retries
        self.router = router or ToolRouter()
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # 图构建
    # ------------------------------------------------------------------
    def _build_graph(self):
        g = StateGraph(ReActState)
        g.add_node("think", self._think)
        g.add_node("act", self._act)
        g.add_node("respond", self._respond)
        g.add_node("degrade", self._degrade)
        g.add_edge(START, "think")
        g.add_conditional_edges("think", self._after_think, {"act": "act", "respond": "respond"})
        g.add_conditional_edges("act", self._after_act, {"think": "think", "degrade": "degrade"})
        g.add_edge("respond", END)
        g.add_edge("degrade", END)
        return g.compile()

    # ------------------------------------------------------------------
    # 节点
    # ------------------------------------------------------------------
    def _think(self, state: dict) -> dict:
        """thinking：由路由器决定下一步工具动作；无动作则进入 responding。"""
        query = state.get("context") or state["user_query"]
        action = self.router.decide(query)
        if action is None:
            return {"pending_action": None, "step": state.get("step", 0) + 1}
        step = state.get("step", 0) + 1
        trace = list(state.get("trace", []))
        trace.append({"step": step, "stage": "acting", "tool": action.name})
        return {
            "pending_action": {"name": action.name, "args": action.args},
            "step": step,
            "trace": trace,
        }

    @staticmethod
    def _after_think(state: dict) -> str:
        return "act" if state.get("pending_action") is not None else "respond"

    def _act(self, state: dict) -> dict:
        """acting：经 safe_call 调用工具（自动重试），失败则进入降级。"""
        pa = state["pending_action"]
        action = ToolAction(name=pa["name"], args=pa.get("args", {}))
        result = call_tool(self.tools.call, action, retries=self.tool_retries, delay=0.0)
        step = state.get("step", 0)
        if isinstance(result, DegradedResult):
            log.error("工具 %s 重试耗尽，进入降级回答", action.name)
            return {"degraded": True, "reason": result.reason}

        # observing：把工具结果转为可观测内容，驱动后续推理 / 回答
        trace = list(state.get("trace", []))
        trace.append({"step": step, "stage": "observing", "tool": action.name})
        observations = list(state.get("observations", []))
        source_chunks = list(state.get("source_chunks", []))
        if action.name == "search_knowledge":
            chunks = result if isinstance(result, list) else []
            observations.append("\n".join(c.text for c in chunks))
            source_chunks = source_chunks + [c for c in chunks]
        else:
            observations.append(json.dumps(result, ensure_ascii=False, default=str))
        return {
            "observations": observations,
            "source_chunks": source_chunks,
            "trace": trace,
            "context": f"{state.get('context', '')} | 工具 {action.name} 已执行",
        }

    def _after_act(self, state: dict) -> str:
        if state.get("degraded"):
            return "degrade"
        if state.get("step", 0) >= self.max_steps:
            return "degrade"
        return "think"

    def _respond(self, state: dict) -> dict:
        """responding：基于观察结果 + 会话历史综合生成最终回答。"""
        answer = self._synthesize(
            state["user_query"],
            state.get("observations", []),
            state.get("source_chunks", []),
            state.get("history", []),
        )
        trace = list(state.get("trace", []))
        trace.append({"step": state.get("step", 0) + 1, "stage": "responding"})
        return {"answer": answer, "degraded": False, "trace": trace}

    def _degrade(self, state: dict) -> dict:
        """degrade：工具失败 / 超步，返回降级回答而非抛异常（G-5）。"""
        if state.get("reason"):
            reason = state["reason"]
            answer = self._degraded_answer(
                state["user_query"], DegradedResult(value=None, reason=reason)
            )
        else:
            reason = "max_steps_exceeded"
            answer = self._degraded_answer(state["user_query"], None, max_steps=True)
        return {"answer": answer, "degraded": True, "reason": reason}

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def run(self, session_id: str, user_query: str, history: list | None = None) -> AgentAnswer:
        """执行一轮售前咨询；``history`` 为该会话先前的多轮消息（可选）。"""
        self.router.reset()
        state = self._graph.invoke(
            {
                "session_id": session_id,
                "user_query": user_query,
                "context": user_query,
                "history": history or [],
                "step": 0,
                "observations": [],
                "source_chunks": [],
                "trace": [],
            }
        )
        return AgentAnswer(
            answer=state.get("answer", ""),
            source_chunks=state.get("source_chunks", []),
            trace=state.get("trace", []),
            degraded=bool(state.get("degraded", False)),
            reason=state.get("reason", ""),
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _synthesize(
        self, query: str, observations: list, chunks: list, history: list | None = None
    ) -> str:
        prompt_lines = ["你是一名售前客服。请基于检索结果与工具结果回答用户问题。"]
        for turn in history or []:
            who = "用户" if turn.get("role") == "user" else "客服"
            prompt_lines.append(f"{who}：{turn.get('content', '')}")
        prompt_lines.append(f"用户问题：{query}")
        for i, obs in enumerate(observations, start=1):
            prompt_lines.append(f"【检索或工具结果 {i}】{obs}")
        for c in chunks[:3]:
            prompt_lines.append(f"【检索片段】{c.text}")
        messages = [{"role": "user", "content": "\n".join(prompt_lines)}]
        return self.llm.generate(messages, mode="answer")

    def _degraded_answer(
        self, query: str, result: DegradedResult | None, max_steps: bool = False
    ) -> str:
        if max_steps:
            return f"抱歉，处理你的问题「{query}」超出最大推理步数，请稍后重试或换个问法。"
        reason = result.reason if result else "未知错误"
        return f"抱歉，当前暂时无法完整回答你的问题「{query}」（原因：{reason}），请稍后再试。"


def _state_snapshot(state: dict) -> dict[str, Any]:
    """调试用：截取状态中非内部字段。"""
    return {k: v for k, v in state.items() if k != "pending_action"}