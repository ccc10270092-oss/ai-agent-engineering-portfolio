"""端到端演示：从原始数据 → 脱敏管道 → 入库 → 售前问答 → 内容生成。

无需任何第三方依赖、无需 API Key 即可运行：
    python demo.py

说明：config.yaml 默认 embedding_backend=local（本地 bge-small-zh-v1.5，
首次运行自动下载约 100MB 模型，国内网络可在 .env 设置
HF_ENDPOINT=https://hf-mirror.com 加速）；未安装 fastembed 时自动回退
内置特征哈希向量，仍可完整离线运行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from service import System  # noqa: E402


def sample_records() -> list[dict]:
    """构造带 PII、重复项、空值的原始客服数据。"""
    return [
        {"session_id": "s1", "user_id": "u1", "role": "user",
         "content": "你好，我的手机号是 13812345678，想咨询智能门锁 S1 的参数。"},
        {"session_id": "s1", "user_id": "u1", "role": "assistant",
         "content": "好的，智能门锁 S1 支持指纹+密码+蓝牙三合一，续航 1 年，价格 899 元。"},
        {"session_id": "s1", "user_id": "u1", "role": "user",
         "content": "那我登记一下，身份证 110101199003078888，邮箱 zhangsan@example.com。"},
        {"session_id": "s2", "user_id": "u2", "role": "user",
         "content": "扫地机器人 R3 现在有货吗？"},
        {"session_id": "s2", "user_id": "u2", "role": "user",
         "content": "扫地机器人 R3 现在有货吗？"},  # 重复
        {"session_id": "s3", "user_id": "u3", "role": "user",
         "content": "   "},  # 空值，应被清洗丢弃
    ]


def sample_knowledge() -> list[tuple[str, str]]:
    return [
        ("智能门锁 S1 参数", "智能门锁 S1 采用指纹、密码、蓝牙三合一开锁，续航一年，售价 899 元，支持远程查看开锁记录。"),
        ("扫地机器人 R3 参数", "扫地机器人 R3 采用激光导航，吸力 5000Pa，续航 180 分钟，售价 1999 元，支持自动回充。"),
        ("智能音箱 M2 参数", "智能音箱 M2 内置语音助手，支持智能家居联动，售价 399 元，支持定时与场景联动。"),
        ("售后服务说明", "本店所有产品支持 7 天无理由退换，整机保修一年，全国联保。"),
    ]


def main() -> None:
    print("=" * 68)
    print("智能 AI Agent 售前服务系统 · 端到端演示")
    print("=" * 68)

    sys_obj = System()

    # 1) 数据脱敏管道
    print("\n[1/4] 数据脱敏管道（清洗 → 去重 → PII 脱敏）")
    records = sample_records()
    masked, report = sys_obj.process_data(records)
    print(f"  输入 {len(records)} 条，输出 {report.total_records} 条")
    print(f"  脱敏命中：{json.dumps(report.mask_hits, ensure_ascii=False)}")
    print(f"  抽样样本：")
    for s in report.samples:
        print(f"    {s['pii_type']}: {s['before']} -> {s['after']}")

    # 2) 知识入库
    print("\n[2/4] 知识入库（切片 → FTS5 全文 + 向量双路）")
    total = 0
    for title, content in sample_knowledge():
        total += sys_obj.ingest_doc(title, content)["chunks"]
    print(f"  已入库 {len(sample_knowledge())} 篇文档，共 {total} 个切片")

    # 3) 售前咨询
    print("\n[3/4] 售前咨询 Agent（ReAct）")
    for q in [
        "智能门锁 S1 的价格和参数？",
        "智能音箱 M2 有库存吗？",
        "你们的售后政策是什么？",
    ]:
        ans = sys_obj.ask("demo-session", q)
        flag = "降级" if ans.degraded else "正常"
        print(f"\n  问：{q}")
        print(f"  答({flag})：{ans.answer}")
        print(f"  trace：{' -> '.join(t['stage'] for t in ans.trace)}")

    # 4) 内容生成
    print("\n[4/4] 内容生成 Agent（选题/文案/脚本）")
    for gc in sys_obj.generate_content(
        "demo-session", {"product_id": "P001", "name": "智能门锁 S1"}
    ):
        print(f"\n  [{gc.stage.value} / {gc.status.value}]")
        print("  " + (gc.content or "（失败，已跳过）").replace("\n", "\n  "))

    print("\n" + "=" * 68)
    print("演示完成")
    print("=" * 68)


if __name__ == "__main__":
    main()