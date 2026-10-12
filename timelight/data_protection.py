"""Read-only SQLite snapshots with verified, non-overwriting publication.

Copying just a .sqlite3 file can miss committed WAL data. Always use SQLite's
online backup API, even when backing up a database owned by another process.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import time


class DataProtectionError(RuntimeError):
    """The database was preserved and requires attention before continuing."""


class UnsupportedSchemaError(DataProtectionError):
    """This application cannot safely write the database's schema version."""


class BackupError(DataProtectionError):
    """No verified backup could be published; callers must not proceed to write."""


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing database without creating it or ignoring its WAL."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA query_only=ON")
    return connection


def verify_integrity(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        detail = "; ".join(str(row[0]) for row in rows[:3])
        raise DataProtectionError(f"数据库完整性检查未通过：{detail}。原文件已保留，请从有效备份恢复。")


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    # Windows rename is atomic and rejects an existing destination. POSIX rename
    # overwrites, so use an atomic hard link there instead. Both files are on the
    # same filesystem because the temporary is created in destination.parent.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
        temporary.unlink()


def backup_database(source: Path, destination: Path) -> Path:
    """Snapshot source (including committed WAL) without modifying its records.

    The destination must not exist. A verified standalone SQLite image is
    flushed to disk and published atomically, never replacing an existing file.
    Uncommitted transactions are intentionally excluded from the snapshot.
    """
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    if destination.resolve() == source:
        raise BackupError("备份目标不能是当前数据库；原文件未修改。")
    if os.path.lexists(destination):
        raise BackupError(f"备份目标已存在，不会覆盖：{destination}")
    if destination.resolve() in {Path(str(source) + suffix) for suffix in ("-wal", "-shm", "-journal")}:
        raise BackupError("备份目标不能是当前数据库的日志文件；原文件未修改。")
    if not source.is_file():
        raise BackupError(f"找不到需要备份的数据库：{source}。没有创建或重置原文件。")

    temporary = None
    reader = None
    writer = None
    try:
        reader = open_readonly(source)
        # Fail before creating a destination directory for a damaged source.
        verify_integrity(reader)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(descriptor)
        temporary = Path(filename)
        writer = sqlite3.connect(str(temporary), timeout=5)
        deadline = time.monotonic() + 30

        def check_deadline(status: int, remaining: int, total: int) -> None:
            if time.monotonic() > deadline:
                raise BackupError("数据库持续忙碌，备份未能在 30 秒内完成。请稍后重试；原文件未修改。")

        reader.backup(writer, pages=128, progress=check_deadline, sleep=0.05)
        writer.commit()
        # Make the published backup self-contained, with no required WAL file.
        mode = writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if mode.lower() != "delete":
            raise BackupError("无法生成独立的备份文件；原文件未修改。")
        verify_integrity(writer)
        writer.close()
        writer = None
        reader.close()
        reader = None
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        _publish_without_overwrite(temporary, destination)
        temporary = None
        return destination
    except DataProtectionError:
        raise
    except (sqlite3.Error, OSError) as error:
        raise BackupError(f"数据库备份失败，原记录已保留，未覆盖任何已有备份：{error}") from error
    finally:
        if writer is not None:
            writer.close()
        if reader is not None:
            reader.close()
        if temporary is not None:
            # Only remove files belonging to this uniquely-created temporary.
            for path in (temporary, *(Path(str(temporary) + suffix) for suffix in ("-wal", "-shm", "-journal"))):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
