"""内容生成三阶段：选题 / 文案 / 脚本（BR-05.1）。

提示词支持 RAG 接地：product_info 携带 `specs`（商品参数串）与
`references`（知识库检索片段 [{"doc_id","title","text"}]，由
System.build_grounding 注入）时追加接地块；两键缺失时提示词与
旧版逐字节一致（向后兼容）。末行 `用户问题：{name}` 为固定标记，
MockLLM._extract_query 依赖它提取查询，接地块必须保持在其之前。
"""
from __future__ import annotations

from app_core.llm import LLMClient
from app_core.models import ContentStage


def _name(product_info: dict) -> str:
    return product_info.get("name") or product_info.get("product_id", "产品")


def _grounding_block(product_info: dict) -> str:
    """接地块：产品参数 + 检索片段；无相关键时返回空串（提示词保持原样）。"""
    specs = str(product_info.get("specs") or "").strip()
    refs = product_info.get("references") or []
    lines = []
    if specs:
        lines.append(f"产品参数：{specs}")
    if refs:
        lines.append("参考资料：")
    for ref in refs:
        if isinstance(ref, dict) and str(ref.get("text") or "").strip():
            title = str(ref.get("title") or "").strip()
            line = f"【检索片段】{str(ref['text']).strip()}"
            lines.append(f"{line}（来源：{title}）" if title else line)
    return "\n".join(lines)


def _prompt(task: str, product_info: dict) -> str:
    name = _name(product_info)
    body = f"为产品【{name}】{task}"
    grounding = _grounding_block(product_info)
    if grounding:
        body += "\n" + grounding + "\n"
    return body + f"用户问题：{name}"


def generate_topic(llm: LLMClient, product_info: dict) -> str:
    return llm.generate(
        [{"role": "user", "content": _prompt("生成 3 个选题。", product_info)}],
        mode="topic",
    )


def generate_copy(llm: LLMClient, product_info: dict) -> str:
    return llm.generate(
        [{"role": "user", "content": _prompt("生成推广文案。", product_info)}],
        mode="copy",
    )


def generate_script(llm: LLMClient, product_info: dict) -> str:
    return llm.generate(
        [{"role": "user", "content": _prompt("生成短视频脚本。", product_info)}],
        mode="script",
    )


STAGE_GENERATORS = {
    ContentStage.TOPIC: generate_topic,
    ContentStage.COPY: generate_copy,
    ContentStage.SCRIPT: generate_script,
}
