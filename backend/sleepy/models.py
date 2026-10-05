"""ORM models.

Data layers (see ARCHITECTURE.md):
  1. Original data  -> RawFile (content addressed, immutable files on disk)
  2. Imported raw   -> Import, ImportFile, DeviceFile (what came from where)
  3. Normalised     -> Night, TherapySession, SignalSegment (+ .npy files), Event
  4. Aggregated     -> NightMetric
  5. Analysis       -> computed on demand from 3/4 (insights, anomalies, reports)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_pending: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ------------------------------------------------------------------- devices
class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("owner_id", "manufacturer", "serial", name="uq_device_owner_serial"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    manufacturer: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial: Mapped[str] = mapped_column(String(64))
    firmware: Mapped[str | None] = mapped_column(String(255), nullable=True)
    series: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data_format: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    identification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------- raw archive
class RawFile(Base):
    """Content addressed original file (sha256).  The file on disk is read-only."""

    __tablename__ = "raw_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Import(Base):
    __tablename__ = "imports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # zip | folder | server_dir | reprocess
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    log: Mapped[list[Any]] = mapped_column(JSON, default=list)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    uploaded_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class ImportFile(Base):
    __tablename__ = "import_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))  # path inside the upload
    sd_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # relative to card root
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    raw_file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_files.id"), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # new|updated|duplicate|ignored|error
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeviceFile(Base):
    """Version history of every card file per device (path -> raw file)."""

    __tablename__ = "device_files"
    __table_args__ = (
        UniqueConstraint("device_id", "rel_path", "raw_file_id", name="uq_device_file_version"),
        Index("ix_device_files_device_path", "device_id", "rel_path"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    rel_path: Mapped[str] = mapped_column(String(1024))
    raw_file_id: Mapped[int] = mapped_column(ForeignKey("raw_files.id"))
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    raw_file: Mapped[RawFile] = relationship()


class ServerFileIndex(Base):
    """Cache for the server import directory (avoid re-hashing unchanged files)."""

    __tablename__ = "server_file_index"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(2048), unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))


# ----------------------------------------------------------- normalised data
class Night(Base):
    __tablename__ = "nights"
    __table_args__ = (UniqueConstraint("device_id", "date", name="uq_night_device_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    start_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usage_s: Mapped[float] = mapped_column(Float, default=0.0)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    has_detail: Mapped[bool] = mapped_column(Boolean, default=False)
    has_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    parser: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(16))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mask_intervals: Mapped[list[Any]] = mapped_column(JSON, default=list)
    channels: Mapped[list[Any]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    storage_gen: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_import_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    device: Mapped[Device] = relationship()
    metrics: Mapped[list[NightMetric]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    sessions: Mapped[list[TherapySession]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="TherapySession.start_ms"
    )


class TherapySession(Base):
    __tablename__ = "therapy_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("nights.id", ondelete="CASCADE"), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    duration_s: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))  # detail | summary
    files: Mapped[list[Any]] = mapped_column(JSON, default=list)


class SignalSegment(Base):
    __tablename__ = "signal_segments"
    __table_args__ = (Index("ix_segments_night_channel", "night_id", "channel"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("nights.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("therapy_sessions.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(16))
    sample_rate: Mapped[float] = mapped_column(Float)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    n_samples: Mapped[int] = mapped_column(Integer)
    gain: Mapped[float] = mapped_column(Float)
    offset: Mapped[float] = mapped_column(Float)
    invalid_digital: Mapped[int | None] = mapped_column(Integer, nullable=True)
    physical_min: Mapped[float] = mapped_column(Float)
    physical_max: Mapped[float] = mapped_column(Float)
    vmin: Mapped[float | None] = mapped_column(Float, nullable=True)
    vmax: Mapped[float | None] = mapped_column(Float, nullable=True)
    vmean: Mapped[float | None] = mapped_column(Float, nullable=True)
    path: Mapped[str] = mapped_column(String(512))
    source_file: Mapped[str] = mapped_column(String(1024))
    raw_file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_files.id"), nullable=True)
    conversion: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_night_start", "night_id", "start_ms"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("nights.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("therapy_sessions.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(16), index=True)
    label: Mapped[str] = mapped_column(String(128))
    onset_ms: Mapped[int] = mapped_column(BigInteger)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str] = mapped_column(String(1024))
    raw_file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_files.id"), nullable=True)


class NightSourceFile(Base):
    __tablename__ = "night_source_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("nights.id", ondelete="CASCADE"), index=True)
    rel_path: Mapped[str] = mapped_column(String(1024))
    raw_file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_files.id"), nullable=True)


# ---------------------------------------------------------------- aggregates
class NightMetric(Base):
    __tablename__ = "night_metrics"
    __table_args__ = (
        UniqueConstraint("night_id", "key", "source", name="uq_night_metric"),
        Index("ix_metric_key_value", "key", "value"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("nights.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))  # device | computed


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


# ------------------------------------------------------------------ hardware
class HardwareItem(Base):
    """User maintained equipment: CPAP device, masks, tubes, filters, ..."""

    __tablename__ = "hardware_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))  # device | mask | cushion | tube | filter | humidifier | other
    name: Mapped[str] = mapped_column(String(128))
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    replace_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    readings: Mapped[list[HardwareReading]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="HardwareReading.read_on"
    )


class HardwareReading(Base):
    """Manually recorded counter value, e.g. blower/turbine hours of the device."""

    __tablename__ = "hardware_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("hardware_items.id", ondelete="CASCADE"), index=True)
    read_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32), default="blower_hours")  # blower_hours | device_hours | other
    value: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
