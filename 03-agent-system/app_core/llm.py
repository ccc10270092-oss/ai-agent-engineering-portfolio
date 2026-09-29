"""LLM 统一调用客户端（满足设计 6.2）。

- 配置了 API Key 时：走 OpenAI 兼容的 ``/chat/completions`` 接口（urllib，无外部依赖）；
- 未配置时：自动回落到离线 MockLLM，保证演示与测试无需真实 Key 也能端到端运行。

所有调用一律经 ``safe_call``，失败自动降级，满足 G-5。

所有生成文本在 ``LLMClient.generate`` 出口统一剥离 emoji（真实模型与
Mock 模式均适用），保证对外的回答/文案不夹杂表情符号。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import LLMConfig
from .logger import get_logger
from .safe_call import safe_call

log = get_logger("app_core.llm")

# 覆盖全部主流 emoji 区块：主表情区(含旗帜/部件)、杂项符号、装饰符号、
# 星形箭头区，以及组合 emoji 的粘合字符(变体选择符/零宽连接符/键帽符)；
# 连同紧邻的单个空格一并删除，避免留下孤立空格。
_EMOJI_RE = re.compile(
    "(?:[ \t]?"
    "["
    "\U0001F000-\U0001FAFF"  # 主 emoji 区(表情/手势/动物/物品/旗帜)
    "\U00002600-\U000027BF"  # 杂项符号 + 装饰符号(☀⚡✂❤✨等)
    "\U00002B00-\U00002BFF"  # 星形/箭头(⭐⬆⬇等)
    "\U0000231A-\U0000231B"  # 手表/沙漏
    "\U000023E9-\U000023FA"  # 播放控制键
    "\U000023CF"             # 光碟/弹出
    "\U000025FD-\U000025FE"  # 小方块
    "\U00002934-\U00002935"  # 弯箭头
    "\U0000303D\U00003297\U00003299"  # 〽 ㊗ ㊙
    "\U0000FE0E-\U0000FE0F"  # 变体选择符(文本/emoji 样式后缀)
    "\U0000200D"             # 零宽连接符(组合 emoji 序列)
    "\U000020E3"             # 键帽组合符(1️⃣ 等)
    "]+"
    "[ \t]?"
    ")+"
)


def _strip_emoji(text: str) -> str:
    """去除文本中的全部 emoji（含组合序列），并收敛删除后残留的多余空格。"""
    cleaned = _EMOJI_RE.sub(" ", text)                             # emoji 连同紧邻空格 → 单个空格
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)                   # 多余空格收敛
    cleaned = re.sub(r" +(?=[，。！？；：、）」』])", "", cleaned)  # 中文标点前不留空格
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)                   # 行尾不留空格
    return cleaned.strip()


class LLMClient:
    """LLM 客户端门面：有 Key 走真实接口，无 Key 走离线 mock。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        if config.api_key and config.base_url:
            if _is_anthropic(config):
                self._impl = _AnthropicCompatibleClient(config)
                log.info(
                    "LLM 使用真实接口：%s（模型 %s，anthropic 格式）",
                    config.base_url, config.model,
                )
            else:
                self._impl = _OpenAICompatibleClient(config)
                log.info("LLM 使用真实接口：%s（模型 %s）", config.base_url, config.model)
        else:
            self._impl = MockLLM(config)
            log.info("未配置 LLM_API_KEY，使用离线 MockLLM（演示/测试模式）")

    def generate(self, messages: list, mode: str = "chat", **overrides) -> str:
        """生成文本，失败时返回降级文案而非抛异常；出口统一剥离 emoji。"""
        result = safe_call(
            self._impl.generate,
            messages,
            mode=mode,
            **overrides,
            retries=overrides.pop("retries", 2),
            delay=1.0,
            degraded_value="",
        )
        if getattr(result, "degraded", False):
            return f"[降级] 模型暂不可用：{result.reason}"
        return _strip_emoji(result)


class MockLLM:
    """离线确定性生成器：按 mode 返回关键词感知的占位内容。

    agent/content 层通过 mode（answer/topic/copy/script/chat）区分用途，
    mock 据此返回结构化、可读的内容，使无 Key 环境也能跑通全链路。
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, messages: list, mode: str = "chat", **overrides) -> str:
        text = "\n".join(
            m.get("content", "") if isinstance(m, dict) else str(m) for m in messages
        )
        query = _extract_query(text)

        if mode == "topic":
            return (
                f"选题一：{query} 的核心卖点解析\n"
                f"选题二：{query} 的 3 个典型使用场景\n"
                f"选题三：{query} 与竞品的差异化对比"
            )
        if mode == "copy":
            return (
                f"【推广文案】{query}，智能生活新选择。"
                f"旗舰配置 × 贴心售后，现在下单立享优惠，点击了解更多。"
            )
        if mode == "script":
            return (
                f"【短视频脚本】\n"
                f"开场：痛点提问——你是否还在为「{query}」的选购而纠结？\n"
                f"中段：三大卖点逐一演示 + 参数特写。\n"
                f"结尾：福利 + 引导评论互动。"
            )
        if mode == "answer":
            # 从上下文抽取「检索片段 / 检索或工具结果」作为回答依据
            facts = _extract_facts(text)
            if facts:
                body = "；".join(facts[:3])
                return f"关于「{query}」，相关答复如下：{body}。"
            return f"关于「{query}」，知识库暂无直接命中，建议补充对应产品资料后再查询。"
        # 默认 chat
        return f"（离线 Mock 回复）已收到你的问题：「{query}」。"


def _extract_query(text: str) -> str:
    """从提示词里尽力抽取用户原始问题。"""
    m = re.search(r"用户问题[:：]\s*(.+)", text)
    if m:
        return m.group(1).strip()
    return text.strip().splitlines()[-1][:80] if text.strip() else ""


def _extract_facts(text: str) -> list:
    """抽取提示词中的「检索片段」与「检索或工具结果」内容。"""
    facts = []
    for line in text.splitlines():
        if "【检索片段】" in line or "【检索或工具结果" in line:
            facts.append(line.split("】", 1)[-1].strip())
    return [f for f in facts if f]


class _OpenAICompatibleClient:
    """极简 OpenAI 兼容客户端，仅依赖标准库 urllib。"""

    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, messages: list, mode: str = "chat", **overrides) -> str:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": _normalize_messages(messages),
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "temperature": overrides.get("temperature", self.config.temperature),
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 用户自配地址
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def _is_anthropic(config: LLMConfig) -> bool:
    """判断端点格式：显式配置优先，否则按 Base URL 自动识别。"""
    fmt = (getattr(config, "api_format", "") or "").strip().lower()
    if fmt in ("anthropic", "openai"):
        return fmt == "anthropic"
    url = config.base_url.lower()
    return "/coding" in url or "anthropic" in url


class _AnthropicCompatibleClient:
    """Anthropic Messages API 兼容客户端（如火山方舟 coding 端点），仅依赖标准库 urllib。

    与 OpenAI 格式的差异：
    - 路径为 ``/v1/messages``，system 提示词是顶层字段而非消息；
    - 响应 content 为分块列表，推理模型附带 thinking 块，只拼接 text 块。
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def generate(self, messages: list, mode: str = "chat", **overrides) -> str:
        url = self.config.base_url.rstrip("/") + "/v1/messages"
        system_parts = [
            m.get("content", "")
            for m in messages if isinstance(m, dict) and m.get("role") == "system"
        ]
        chat = [
            {"role": m["role"], "content": m.get("content", "")}
            for m in messages
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        ]
        payload = {
            "model": self.config.model,
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "temperature": overrides.get("temperature", self.config.temperature),
            "messages": chat,
        }
        if system_parts:
            payload["system"] = "\n".join(p for p in system_parts if p)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        # 推理模型思考耗时较长，放宽到 120s
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - 用户自配地址
            data = json.loads(resp.read().decode("utf-8"))
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )


def _normalize_messages(messages: list) -> list:
    out = []
    for m in messages:
        if isinstance(m, dict) and "role" in m and "content" in m:
            out.append({"role": m["role"], "content": m["content"]})
    return out