"""Alembic migrations, run programmatically (no alembic.ini needed)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

HERE = Path(__file__).resolve().parent


def alembic_config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    cfg.attributes["engine"] = engine
    return cfg


def upgrade_to_head(engine: Engine) -> None:
    command.upgrade(alembic_config(engine), "head")
