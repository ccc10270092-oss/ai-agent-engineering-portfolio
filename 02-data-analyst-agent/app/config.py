from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str | None
    model: str
    admin_token: str
    data_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "shop_analytics.sqlite3"


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "runtime-data")))
    if not data_dir.is_absolute():
        data_dir = (ROOT_DIR / data_dir).resolve()
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    return Settings(
        api_key=os.getenv("LLM_API_KEY", "").strip(),
        base_url=base_url or None,
        model=os.getenv("LLM_MODEL", "your-openai-compatible-model").strip(),
        admin_token=os.getenv("ADMIN_TOKEN", "dev-admin-change-me"),
        data_dir=data_dir,
    )


settings = load_settings()
