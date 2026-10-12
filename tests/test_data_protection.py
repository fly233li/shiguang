import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from timelight import data_protection, storage
from timelight.data_protection import BackupError, DataProtectionError, UnsupportedSchemaError, backup_database
from timelight.storage import APP_VERSION_SETTING, Store


def snapshot(path):
    connection = data_protection.open_readonly(path)
    try:
        return {
            "version": connection.execute("PRAGMA user_version").fetchone()[0],
            "intervals": connection.execute("SELECT * FROM intervals ORDER BY id").fetchall(),
            "settings": connection.execute("SELECT * FROM settings ORDER BY key").fetchall(),
            "schema": connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
        }
    finally:
        connection.close()


class DataProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "usage.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, version=None):
        store = Store(self.path, app_version=version)
        store.add_interval(1700000000, 1700000080, "active", "editor", "编辑器", "C:\\软件\\editor.exe")
        store.add_interval(1700000080, 1700000100, "idle")
        store.set_setting("preferences", {"idle_seconds": 300, "theme": "浅色", "enabled": True})
        store.set_setting("window_size", [1200, 800])
        store.close()

    def backups(self):
        return sorted((self.root / "backups").glob("usage-*.sqlite3"))

    def test_legacy_upgrade_preserves_intervals_apps_and_preferences(self):
        self.seed()
        original = snapshot(self.path)
        upgraded = Store(self.path, app_version="1.1.0")
        try:
            self.assertEqual(upgraded.get_setting(APP_VERSION_SETTING), "1.1.0")
            self.assertEqual(upgraded.get_setting("preferences")["theme"], "浅色")
            self.assertEqual(upgraded.backup_directory, self.root / "backups")
            self.assertEqual(upgraded.latest_backup(), self.backups()[0])
        finally:
            upgraded.close()
        self.assertEqual(len(self.backups()), 1)
        self.assertIn("-upgrade-", self.backups()[0].name)
        self.assertEqual(snapshot(self.backups()[0]), original)
        after = snapshot(self.path)
        self.assertEqual(after["version"], 1)
        self.assertEqual(after["intervals"], original["intervals"])
        self.assertEqual(after["schema"], original["schema"])
        self.assertEqual([row for row in after["settings"] if row[0] != APP_VERSION_SETTING], original["settings"])

    def test_new_database_records_version_without_upgrade_backup(self):
        store = Store(self.path, app_version="1.1.0")
        self.assertEqual(store.get_setting(APP_VERSION_SETTING), "1.1.0")
        self.assertIsNone(store.latest_backup())
        store.close()
        self.assertEqual(self.backups(), [])
        self.assertEqual(snapshot(self.path)["version"], 1)

    def test_default_constructor_neither_backs_up_nor_changes_version_metadata(self):
        self.seed()
        before = snapshot(self.path)
        Store(self.path).close()
        self.assertEqual(snapshot(self.path), before)
        self.assertEqual(self.backups(), [])

    def test_same_version_does_not_repeat_backup_and_switches_keep_history(self):
        self.seed("1.0.2")
        Store(self.path, app_version="1.1.0").close()
        first = self.backups()[0]
        first_bytes = first.read_bytes()
        Store(self.path, app_version="1.1.0").close()
        self.assertEqual(len(self.backups()), 1)
        # App-version switches are allowed only while the schema is supported.
        Store(self.path, app_version="1.0.2").close()
        self.assertEqual(len(self.backups()), 2)
        self.assertEqual(first.read_bytes(), first_bytes)
        latest_version = dict(snapshot(self.path)["settings"])[APP_VERSION_SETTING]
        self.assertEqual(json.loads(latest_version), "1.0.2")

    def test_upgrade_backup_failure_prevents_all_version_or_schema_writes(self):
        self.seed("1.0.2")
        original = snapshot(self.path)
        original_bytes = self.path.read_bytes()
        with patch("timelight.storage.backup_database", side_effect=BackupError("磁盘空间不足")):
            with self.assertRaisesRegex(BackupError, "磁盘空间不足"):
                Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(snapshot(self.path), original)
        self.assertEqual(self.backups(), [])

    def test_unknown_high_schema_is_not_downgraded_or_modified(self):
        self.seed("9.0.0")
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version=99")
        connection.close()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(UnsupportedSchemaError, "格式版本为 99"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(snapshot(self.path)["version"], 99)
        self.assertEqual(self.backups(), [])

    def test_unknown_schema_zero_with_existing_data_is_not_reinitialized(self):
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE old_records(value TEXT)")
        connection.execute("INSERT INTO old_records VALUES('must survive')")
        connection.commit()
        connection.close()
        before = self.path.read_bytes()
        with self.assertRaises(UnsupportedSchemaError):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_database_is_not_deleted_or_rebuilt(self):
        original = b"This file is damaged, but could contain recoverable records.\x00\xff"
        self.path.write_bytes(original)
        with self.assertRaisesRegex(DataProtectionError, "原文件已保留"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_missing_required_table_rejected_without_schema_repair(self):
        self.seed()
        connection = sqlite3.connect(self.path)
        connection.execute("DROP TABLE settings")
        connection.close()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(DataProtectionError, "缺少必要的数据表 settings"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_required_column_rejected_without_schema_repair(self):
        self.seed()
        connection = sqlite3.connect(self.path)
        connection.execute("ALTER TABLE intervals RENAME COLUMN exe_path TO legacy_path")
        connection.close()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(DataProtectionError, "缺少必要字段：exe_path"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), original)

    def test_backup_contains_committed_wal_data_while_source_stays_open(self):
        store = Store(self.path)
        store._db.execute("PRAGMA wal_autocheckpoint=0")
        store.add_interval(1700000000, 1700000090, "active", "browser", "浏览器")
        store.set_setting("live_wal", "已提交")
        original = snapshot(self.path)
        wal = Path(str(self.path) + "-wal")
        self.assertTrue(wal.exists() and wal.stat().st_size > 0)
        destination = self.root / "external" / "snapshot.sqlite3"
        try:
            backup_database(self.path, destination)
            self.assertEqual(snapshot(destination), original)
            self.assertEqual(snapshot(self.path), original)
            self.assertFalse(Path(str(destination) + "-wal").exists())
            self.assertFalse(Path(str(destination) + "-shm").exists())
        finally:
            store.close()

    def test_backup_excludes_uncommitted_transaction(self):
        store = Store(self.path)
        store.set_setting("committed", True)
        store._db.execute("BEGIN IMMEDIATE")
        store._db.execute("INSERT INTO settings VALUES('uncommitted', 'true')")
        try:
            destination = store.create_backup()
            values = dict(snapshot(destination)["settings"])
            self.assertIn("committed", values)
            self.assertNotIn("uncommitted", values)
        finally:
            store._db.rollback()
            store.close()

    def test_upgrade_backup_sees_committed_wal_from_running_legacy_store(self):
        legacy = Store(self.path)
        legacy._db.execute("PRAGMA wal_autocheckpoint=0")
        legacy.add_interval(1700000000, 1700000070, "active", "editor", "编辑器")
        legacy.set_setting("live", [1, 2, 3])
        before = snapshot(self.path)
        try:
            upgraded = Store(self.path, app_version="1.1.0")
            try:
                self.assertEqual(snapshot(upgraded.latest_backup()), before)
            finally:
                upgraded.close()
        finally:
            legacy.close()

    def test_existing_target_and_source_target_are_never_overwritten(self):
        self.seed()
        target = self.root / "existing.sqlite3"
        target.write_bytes(b"Do not overwrite")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(BackupError, "目标已存在"):
            backup_database(self.path, target)
        with self.assertRaisesRegex(BackupError, "不能是当前数据库"):
            backup_database(self.path, self.path)
        self.assertEqual(target.read_bytes(), b"Do not overwrite")
        self.assertEqual(self.path.read_bytes(), before)

    def test_backup_integrity_failure_does_not_publish_or_leave_temp_files(self):
        self.seed()
        target = self.root / "backups" / "broken.sqlite3"
        original = snapshot(self.path)
        check = data_protection.verify_integrity
        calls = 0

        def fail_destination(connection):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise DataProtectionError("模拟备份完整性失败")
            return check(connection)

        with patch("timelight.data_protection.verify_integrity", side_effect=fail_destination):
            with self.assertRaisesRegex(DataProtectionError, "完整性失败"):
                backup_database(self.path, target)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.iterdir()), [])
        self.assertEqual(snapshot(self.path), original)

    def test_destination_race_does_not_overwrite_rivals_file(self):
        self.seed()
        target = self.root / "backups" / "raced.sqlite3"
        publish = data_protection._publish_without_overwrite

        def create_rival_then_publish(temporary, destination):
            destination.write_bytes(b"another backup arrived first")
            publish(temporary, destination)

        with patch("timelight.data_protection._publish_without_overwrite", side_effect=create_rival_then_publish):
            with self.assertRaises(BackupError):
                backup_database(self.path, target)
        self.assertEqual(target.read_bytes(), b"another backup arrived first")
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_metadata_transaction_failure_preserves_original_data_and_backup(self):
        self.seed("1.0.2")
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TRIGGER reject_version BEFORE INSERT ON settings "
            "WHEN NEW.key='app_version' BEGIN SELECT RAISE(ABORT, 'version write rejected'); END"
        )
        connection.close()
        before = snapshot(self.path)
        with self.assertRaisesRegex(DataProtectionError, "version write rejected"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(snapshot(self.path), before)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(snapshot(self.backups()[0]), before)

    def test_initial_schema_creation_failure_rolls_back_every_table_and_version(self):
        create = storage._create_schema

        def create_then_fail(connection):
            create(connection)
            raise sqlite3.OperationalError("simulated initialization failure")

        with patch("timelight.storage._create_schema", side_effect=create_then_fail):
            with self.assertRaisesRegex(DataProtectionError, "initialization failure"):
                Store(self.path, app_version="1.1.0")
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master").fetchall(), [])
        finally:
            connection.close()

    def test_missing_primary_database_with_backups_never_creates_empty_history(self):
        self.seed()
        store = Store(self.path)
        backup = store.create_backup()
        store.close()
        backup_bytes = backup.read_bytes()
        self.path.unlink()
        with self.assertRaisesRegex(DataProtectionError, "停止创建空数据库"):
            Store(self.path, app_version="1.1.0")
        self.assertFalse(self.path.exists())
        self.assertEqual(backup.read_bytes(), backup_bytes)

    def test_truncated_primary_with_existing_backups_is_not_reinitialized(self):
        self.seed()
        store = Store(self.path)
        backup = store.create_backup()
        store.close()
        before = backup.read_bytes()
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(DataProtectionError, "可能被清空或截断"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(len(self.backups()), 1)

    def test_empty_sqlite_schema_with_existing_backups_is_not_reinitialized(self):
        self.seed()
        store = Store(self.path)
        store.create_backup()
        store.close()
        self.path.unlink()
        connection = sqlite3.connect(self.path)
        connection.execute("VACUUM")
        connection.close()
        before = self.path.read_bytes()
        self.assertGreater(len(before), 0)
        with self.assertRaisesRegex(DataProtectionError, "可能被清空或截断"):
            Store(self.path, app_version="1.1.0")
        self.assertEqual(self.path.read_bytes(), before)

    def test_incompatible_primary_key_or_column_type_is_rejected(self):
        for table, definition in (
            ("settings", "key TEXT, value TEXT NOT NULL, PRIMARY KEY(key,value)"),
            ("settings", "key INTEGER PRIMARY KEY, value TEXT NOT NULL"),
            ("intervals", "id TEXT PRIMARY KEY, start REAL, end REAL, day TEXT, hour INTEGER, state TEXT, app_key TEXT, app_name TEXT, exe_path TEXT"),
        ):
            with self.subTest(table=table, definition=definition):
                path = self.root / f"schema-{len(list(self.root.glob('schema-*.sqlite3')))}.sqlite3"
                Store(path).close()
                connection = sqlite3.connect(path)
                connection.execute(f"DROP TABLE {table}")
                connection.execute(f"CREATE TABLE {table} ({definition})")
                connection.close()
                before = path.read_bytes()
                with self.assertRaisesRegex(DataProtectionError, "结构不兼容"):
                    Store(path, app_version="1.1.0")
                self.assertEqual(path.read_bytes(), before)

    def test_background_backup_does_not_lock_sampling_and_snapshot_is_consistent(self):
        self.seed()
        store = Store(self.path)
        entered = Event()
        release = Event()
        check = data_protection.verify_integrity
        calls = 0

        def pause_first_check(connection):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test backup was never released")
            return check(connection)

        try:
            with patch("timelight.data_protection.verify_integrity", side_effect=pause_first_check):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    backup_future = executor.submit(store.create_backup)
                    try:
                        self.assertTrue(entered.wait(2))
                        # Must finish while the backup is still deliberately held.
                        write_future = executor.submit(store.add_interval, 1700000100, 1700000110, "active", "new_app", "新软件")
                        write_future.result(timeout=2)
                    finally:
                        release.set()
                    backup = backup_future.result(timeout=5)
            saved = snapshot(backup)
            self.assertEqual(saved, snapshot(self.path))
            self.assertEqual(saved["intervals"][-1][6], "new_app")
        finally:
            release.set()
            store.close()

    def test_manual_backups_are_unique_and_no_history_is_rotated(self):
        self.seed()
        store = Store(self.path)
        try:
            first = store.create_backup()
            first_bytes = first.read_bytes()
            second = store.create_backup()
            self.assertNotEqual(first, second)
            self.assertEqual(store.latest_backup(), second)
            self.assertEqual(first.read_bytes(), first_bytes)
            self.assertEqual(len(self.backups()), 2)
        finally:
            store.close()

    def test_backup_of_nonexistent_source_does_not_create_it(self):
        with self.assertRaisesRegex(BackupError, "找不到"):
            backup_database(self.path, self.root / "backup.sqlite3")
        self.assertFalse(self.path.exists())
        self.assertFalse((self.root / "backup.sqlite3").exists())

    def test_unreadable_backup_directory_is_not_treated_as_new_user(self):
        with patch("pathlib.Path.iterdir", side_effect=PermissionError("access denied")):
            with self.assertRaisesRegex(DataProtectionError, "无法读取备份目录"):
                Store(self.path, app_version="1.1.0")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
