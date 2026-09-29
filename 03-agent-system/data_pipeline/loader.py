"""数据加载：优先 pandas，缺失时退化为标准库 csv/json。"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def load_records(path: str | Path) -> list[dict]:
    """从 CSV / JSON 文件读取原始客服数据，统一返回 list[dict]。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(path)
    if suffix in (".json", ".jsonl"):
        return _load_json(path)
    raise ValueError(f"不支持的格式：{suffix}")


def _load_csv(path: Path) -> list[dict]:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        pd = None
    if pd is not None:
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _load_json(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    return data if isinstance(data, list) else [data]