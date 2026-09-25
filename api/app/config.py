"""Application settings, read only from environment variables (§9).

No config files are read, so Phase B can inject every value from AWS Secrets
Manager or Parameter Store.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    app_env: str = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    enable_api_docs: bool = False
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"

    # Build info, passed as image build args and served by /version.
    app_version: str = "unknown"
    git_sha: str = "unknown"
    build_time: str = "unknown"

    # The app refuses to start without a strong ingest key.
    ingest_api_key: SecretStr = Field(min_length=32)

    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "dora"
    db_user: str = "dora_app"
    db_password: SecretStr = SecretStr("")
    db_ssl_mode: Literal["disable", "require", "verify-full"] = "disable"
    db_ssl_root_cert: str = ""
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
