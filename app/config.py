from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str | None
    llm_model: str
    admin_token: str
    data_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aftercare.sqlite3"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite3"


def get_settings() -> Settings:
    raw_data_dir = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
    if not raw_data_dir.is_absolute():
        raw_data_dir = (ROOT_DIR / raw_data_dir).resolve()

    base_url = os.getenv("LLM_BASE_URL", "").strip()
    return Settings(
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_base_url=base_url or None,
        llm_model=os.getenv("LLM_MODEL", "your-openai-compatible-model").strip(),
        admin_token=os.getenv("ADMIN_TOKEN", "dev-admin-change-me"),
        data_dir=raw_data_dir,
    )


settings = get_settings()
