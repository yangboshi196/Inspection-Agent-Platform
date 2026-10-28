"""Pydantic Settings：从仓库根目录 `.env` 加载 MySQL / Milvus / 静态资源等配置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(repo_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MySQL（SQLAlchemy）
    database_url: str = Field(
        default="mysql+pymysql://user:your_password@127.0.0.1:3306/security_risk",
        alias="DATABASE_URL",
    )

    # Milvus
    milvus_host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_db_dir: str = Field(default="milvus_db", alias="MILVUS_DB_DIR")

    # 静态资源：仓库 data/ 目录
    data_dir: str = Field(default="data", alias="DATA_DIR")

    # 平台 HTTP
    platform_host: str = Field(default="127.0.0.1", alias="SIA_PLATFORM_HOST")
    platform_port: int = Field(default=8001, alias="SIA_PLATFORM_PORT")

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("mysql://"):
            return "mysql+pymysql://" + url[len("mysql://") :]
        return url

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if p.is_absolute():
            return p
        return (repo_root() / p).resolve()

    @property
    def milvus_persist_path(self) -> Path:
        p = Path(self.milvus_db_dir)
        if p.is_absolute():
            return p
        return (repo_root() / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
