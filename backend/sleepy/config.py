"""Application configuration (environment variables / .env file).

All variables use the prefix ``SLEEPY_``.  See ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SLEEPY_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- general
    data_dir: Path = Path("/var/lib/sleepy")
    database_url: str | None = None  # default: sqlite in data_dir
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_dir: Path | None = None  # default: data_dir/logs
    frontend_dist: Path | None = None  # default: <repo>/frontend/dist
    config_file: Path | None = None  # path of the env file, included in backups

    # --- security
    cookie_secure: str = "auto"  # auto | true | false
    session_idle_minutes: int = 480
    session_max_days: int = 7
    login_rate_limit: int = 10  # attempts per window per IP / username
    login_rate_window_minutes: int = 15
    trusted_proxies: str = "127.0.0.1"  # comma separated, '*' = any
    allowed_origins: str = ""  # extra origins allowed for state changing requests
    enable_api_docs: bool = True

    # --- import
    max_upload_mb: int = 8192
    max_unzipped_mb: int = 20480
    import_dir: Path | None = None  # server side import directory
    import_scan_interval_minutes: int = 0  # 0 = no automatic scanning
    staging_retention_days: int = 7

    # --- analysis
    leak_threshold: float = Field(24.0, description="Leckage-Schwelle L/min (ResMed-Konvention)")

    # --- backup
    backup_dir: Path | None = None  # default: data_dir/backups
    backup_keep: int = 10

    @field_validator("cookie_secure")
    @classmethod
    def _cs(cls, v: str) -> str:
        v = v.lower()
        if v not in ("auto", "true", "false"):
            raise ValueError("cookie_secure must be auto|true|false")
        return v

    # derived paths --------------------------------------------------------
    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'db' / 'sleepy.db').as_posix()}"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def signals_dir(self) -> Path:
        return self.data_dir / "signals"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def logs_dir(self) -> Path:
        return self.log_dir or (self.data_dir / "logs")

    @property
    def backups_dir(self) -> Path:
        return self.backup_dir or (self.data_dir / "backups")

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def frontend_path(self) -> Path:
        if self.frontend_dist:
            return self.frontend_dist
        return Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [x.strip() for x in self.trusted_proxies.split(",") if x.strip()]

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.data_dir / "db",
            self.raw_dir,
            self.signals_dir,
            self.staging_dir,
            self.logs_dir,
            self.backups_dir,
            self.exports_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
