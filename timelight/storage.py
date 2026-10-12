"""Local, durable usage intervals. All durations are elapsed seconds.

Intervals are half-open [start, end). ``awake`` includes every recorded state;
``active`` and app usage include only active foreground use. The local date and
hour are saved when recording, so later timezone changes do not move history.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .data_protection import (
    BackupError, DataProtectionError, UnsupportedSchemaError,
    backup_database, open_readonly, verify_integrity,
)


STATES = ("active", "idle", "locked", "paused", "unknown")
SCHEMA_VERSION = 1
APP_VERSION_SETTING = "app_version"
REQUIRED_COLUMNS = {
    "intervals": {"id": "INTEGER", "start": "REAL", "end": "REAL", "day": "TEXT", "hour": "INTEGER",
                  "state": "TEXT", "app_key": "TEXT", "app_name": "TEXT", "exe_path": "TEXT"},
    "settings": {"key": "TEXT", "value": "TEXT"},
}


def _validate_schema(connection: sqlite3.Connection) -> int:
    """Read-only compatibility gate; never lower user_version or repair a table."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    objects = connection.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if version == 0 and not objects:
        return 0
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"这份记录数据库的格式版本为 {version}，当前程序仅支持格式版本 {SCHEMA_VERSION}。"
            "已停止写入，原记录未修改；请使用兼容版本的时光计打开，或从有效备份恢复。"
        )
    tables = {row[1] for row in objects if row[0] == "table"}
    for table, expected in REQUIRED_COLUMNS.items():
        if table not in tables:
            raise DataProtectionError(f"记录数据库缺少必要的数据表 {table}。原文件已保留，不会自动重建；请从有效备份恢复。")
        columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
        missing = expected.keys() - {column[1] for column in columns}
        if missing:
            raise DataProtectionError(
                f"记录数据库的数据表 {table} 缺少必要字段：{', '.join(sorted(missing))}。"
                "原文件已保留，不会自动重建；请从有效备份恢复。"
            )
        primary_key = "id" if table == "intervals" else "key"
        primary_keys = [column[1] for column in columns if column[5] > 0]
        incompatible_types = [column[1] for column in columns
                              if column[1] in expected and column[2].strip().upper() != expected[column[1]]]
        if primary_keys != [primary_key] or incompatible_types:
            raise DataProtectionError(f"记录数据库的数据表 {table} 结构不兼容。原文件已保留，请使用兼容版本或有效备份。")
    return version


def _create_schema(connection: sqlite3.Connection) -> None:
    """Called only inside the initial explicit transaction for an empty DB."""
    connection.execute(
        """CREATE TABLE intervals (
            id INTEGER PRIMARY KEY,
            start REAL NOT NULL,
            end REAL NOT NULL CHECK (end > start),
            day TEXT NOT NULL,
            hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
            state TEXT NOT NULL CHECK (state IN ('active', 'idle', 'locked', 'paused', 'unknown')),
            app_key TEXT NOT NULL DEFAULT '',
            app_name TEXT NOT NULL DEFAULT '',
            exe_path TEXT NOT NULL DEFAULT ''
        )"""
    )
    connection.execute("CREATE INDEX intervals_day ON intervals(day)")
    connection.execute("CREATE INDEX intervals_end ON intervals(end)")
    connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("PRAGMA user_version=1")


def _hour_parts(start: float, end: float):
    """Split at local hour boundaries, including a repeated DST hour.

    Naive datetime.timestamp uses the operating system's local timezone and
    supports fold. Both occurrences of a repeated hour share the chart's bin.
    """
    while start < end:
        local = datetime.fromtimestamp(start)
        floor = local.replace(minute=0, second=0, microsecond=0)
        candidates = [end]
        for wall in (floor, floor + timedelta(hours=1)):
            for fold in (0, 1):
                boundary = wall.replace(fold=fold).timestamp()
                if boundary > start + 0.000001:
                    candidates.append(boundary)
        stop = min(candidates)
        yield start, stop, local.date().isoformat(), local.hour
        start = stop


def _date_range(start_date: date, end_date: date) -> tuple[str, str]:
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise TypeError("日期必须是 datetime.date")
    if end_date < start_date:
        raise ValueError("结束日期不能早于开始日期")
    return start_date.isoformat(), end_date.isoformat()


class Store:
    def __init__(self, path: Path, *, app_version: str | None = None):
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        if app_version is not None and (not isinstance(app_version, str) or not app_version.strip()):
            raise ValueError("应用版本必须是非空字符串")
        existed = self.path.exists()
        if not existed and self.latest_backup() is not None:
            raise DataProtectionError(
                f"记录数据库不见了，但在 {self.backup_directory} 找到了历史备份。"
                "为避免把记录丢失误当作首次使用，已停止创建空数据库；请先从有效备份恢复。"
            )
        previous_version = None
        schema = 0
        self._db = None
        try:
            if existed:
                reader = open_readonly(self.path)
                try:
                    # This gate runs before opening any writable connection.
                    schema = _validate_schema(reader)
                    verify_integrity(reader)
                    if schema == 0 and self.latest_backup() is not None:
                        raise DataProtectionError(
                            f"当前记录数据库为空，但在 {self.backup_directory} 找到了历史备份。"
                            "数据库可能被清空或截断，已停止初始化；请先从有效备份恢复记录。"
                        )
                    if schema and app_version is not None:
                        row = reader.execute("SELECT value FROM settings WHERE key=?", (APP_VERSION_SETTING,)).fetchone()
                        if row:
                            previous_version = json.loads(row[0])
                finally:
                    reader.close()
                if app_version is not None and previous_version != app_version:
                    # No metadata or schema writes may occur before this returns.
                    self.create_backup("upgrade")

            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.path), timeout=5, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            # Recheck compatibility after opening to fail safely on a changed DB.
            schema = _validate_schema(self._db)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            if schema == 0 or (app_version is not None and previous_version != app_version):
                self._prepare_schema_and_version(schema, app_version)
        except Exception as error:
            if self._db is not None:
                self._db.close()
                self._db = None
            if isinstance(error, DataProtectionError):
                raise
            if isinstance(error, (sqlite3.Error, OSError, ValueError)):
                raise DataProtectionError(
                    f"无法安全打开记录数据库：{error}。原文件已保留，不会删除或自动重建；"
                    "请检查文件权限、使用兼容版本，或从有效备份恢复。"
                ) from error
            raise

    def _prepare_schema_and_version(self, schema: int, app_version: str | None) -> None:
        """Atomic migration boundary; schema 1 currently needs no migration.

        Future supported migrations belong in this transaction and must only be
        reached after a verified upgrade backup. Do not use executescript here:
        it may implicitly commit before the migration has completely succeeded.
        """
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if schema == 0:
                _create_schema(self._db)
            elif schema != SCHEMA_VERSION:
                raise UnsupportedSchemaError("数据库格式不兼容，已取消更新；原记录未修改。")
            _validate_schema(self._db)
            if app_version is not None:
                self._db.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (APP_VERSION_SETTING, json.dumps(app_version)),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    @property
    def backup_directory(self) -> Path:
        return self.path.parent / "backups"

    def create_backup(self, reason: str = "manual") -> Path:
        """Keep every manual/upgrade snapshot; never rotate version history."""
        label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(reason)).strip("-")[:40] or "manual"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = self.backup_directory / f"{self.path.stem}-{label}-{stamp}-{uuid4().hex[:12]}.sqlite3"
        # A separate read-only connection provides a consistent SQLite snapshot.
        # Do not hold the store lock: a background backup must not stop sampling.
        return backup_database(self.path, destination)

    def latest_backup(self) -> Path | None:
        try:
            # iterdir surfaces access errors; glob may silently hide them and
            # make an unreadable backup directory look like no history exists.
            paths = list(self.backup_directory.iterdir())
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DataProtectionError(
                f"无法读取备份目录 {self.backup_directory}，不能确认历史记录是否完整。"
                f"请检查目录权限后重试：{error}"
            ) from error
        candidates = [path for path in paths if path.name.startswith(f"{self.path.stem}-")
                      and path.suffix == ".sqlite3" and path.is_file()]
        try:
            return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)
        except OSError as error:
            raise DataProtectionError(f"无法读取备份文件信息，原记录未修改：{error}") from error

    def add_interval(
        self, start: float, end: float, state: str,
        app_key: str = "", app_name: str = "", exe_path: str = "",
    ) -> None:
        start, end = float(start), float(end)
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("记录区间必须是有限数值，且结束时间晚于开始时间")
        if start < 0 or end > time.time() + 5:
            raise ValueError("不能记录无效日期或尚未发生的时间")
        if state not in STATES:
            raise ValueError(f"未知记录状态：{state}")
        if state != "active":
            app_key = app_name = exe_path = ""
        with self._lock, self._db:
            overlap = self._db.execute(
                "SELECT 1 FROM intervals WHERE end > ? AND start < ? LIMIT 1",
                (start, end),
            ).fetchone()
            if overlap:
                raise ValueError("记录区间重叠，已拒绝重复计时")
            for a, b, day, hour in _hour_parts(start, end):
                previous = self._db.execute(
                    "SELECT * FROM intervals WHERE end = ? ORDER BY id DESC LIMIT 1",
                    (a,),
                ).fetchone()
                identity = (day, hour, state, app_key, app_name, exe_path)
                if previous and tuple(previous[k] for k in
                    ("day", "hour", "state", "app_key", "app_name", "exe_path")) == identity:
                    self._db.execute("UPDATE intervals SET end = ? WHERE id = ?", (b, previous["id"]))
                else:
                    self._db.execute(
                        "INSERT INTO intervals(start,end,day,hour,state,app_key,app_name,exe_path) "
                        "VALUES(?,?,?,?,?,?,?,?)", (a, b, *identity),
                    )

    def get_summary(self, start_date: date, end_date: date) -> dict[str, float]:
        bounds = _date_range(start_date, end_date)
        result = {key: 0.0 for key in ("awake", *STATES)}
        with self._lock:
            rows = self._db.execute(
                "SELECT state, SUM(end-start) AS seconds FROM intervals "
                "WHERE day BETWEEN ? AND ? GROUP BY state", bounds,
            ).fetchall()
        for row in rows:
            result[row["state"]] = float(row["seconds"])
            result["awake"] += float(row["seconds"])
        return result

    def get_apps(self, start_date: date, end_date: date) -> list[dict]:
        bounds = _date_range(start_date, end_date)
        with self._lock:
            rows = self._db.execute(
                "SELECT app_key AS key, MAX(app_name) AS name, MAX(exe_path) AS path, "
                "SUM(end-start) AS seconds FROM intervals WHERE day BETWEEN ? AND ? "
                "AND state='active' AND app_key<>'' GROUP BY app_key "
                "ORDER BY seconds DESC, name COLLATE NOCASE", bounds,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_hourly(self, day: date) -> list[dict]:
        result = [{"hour": hour, "awake": 0.0, "active": 0.0} for hour in range(24)]
        with self._lock:
            rows = self._db.execute(
                "SELECT hour, SUM(end-start) AS awake, "
                "SUM(CASE WHEN state='active' THEN end-start ELSE 0 END) AS active "
                "FROM intervals WHERE day=? GROUP BY hour", (day.isoformat(),),
            ).fetchall()
        for row in rows:
            result[row["hour"]].update(dict(row))
        return result

    def get_daily(self, start_date: date, end_date: date) -> list[dict]:
        bounds = _date_range(start_date, end_date)
        with self._lock:
            rows = self._db.execute(
                "SELECT day AS date, SUM(end-start) AS awake, "
                "SUM(CASE WHEN state='active' THEN end-start ELSE 0 END) AS active "
                "FROM intervals WHERE day BETWEEN ? AND ? GROUP BY day", bounds,
            ).fetchall()
        by_day = {row["date"]: dict(row) for row in rows}
        result = []
        day = start_date
        while day <= end_date:
            label = day.isoformat()
            result.append(by_day.get(label, {"date": label, "awake": 0.0, "active": 0.0}))
            day += timedelta(days=1)
        return result

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encoded),
            )

    @property
    def first_recorded(self) -> float | None:
        with self._lock:
            return self._db.execute("SELECT MIN(start) FROM intervals").fetchone()[0]

    @property
    def last_recorded(self) -> float | None:
        """End boundary used to avoid overlap after the system clock rolls back."""
        with self._lock:
            return self._db.execute("SELECT MAX(end) FROM intervals").fetchone()[0]

    def export_csv(self, path: Path, start_date: date, end_date: date) -> None:
        bounds = _date_range(start_date, end_date)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM intervals WHERE day BETWEEN ? AND ? ORDER BY start", bounds,
            ).fetchall()
        states = {"active": "使用中", "idle": "空闲", "locked": "锁屏", "paused": "已暂停", "unknown": "未识别"}
        def safe_text(value: str) -> str:
            return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
        with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["日期", "小时", "开始时间", "结束时间", "状态", "软件名称", "程序路径", "时长（秒）"])
            for row in rows:
                writer.writerow([
                    row["day"], row["hour"],
                    datetime.fromtimestamp(row["start"]).astimezone().isoformat(timespec="seconds"),
                    datetime.fromtimestamp(row["end"]).astimezone().isoformat(timespec="seconds"),
                    states[row["state"]], safe_text(row["app_name"]), safe_text(row["exe_path"]),
                    round(row["end"] - row["start"], 3),
                ])

    def close(self) -> None:
        with self._lock:
            self._db.close()
