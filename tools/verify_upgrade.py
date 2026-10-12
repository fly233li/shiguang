"""Exercise an in-place upgrade using two real packaged Windows executables.

The executables use the SAME installation and default data path, but their
LOCALAPPDATA and instance mutex are isolated from the user's running app. Raw
intervals remain in memory / the temporary test directory; the JSON report
contains only checks, counts, durations, and hashes. No existing process is
stopped and no startup registry setting is changed.

Example:
    .venv\\Scripts\\python.exe tools\\verify_upgrade.py
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, time as day_time, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from timelight import __version__ as CURRENT_VERSION

APPLICATION_VERSION_KEY = "app_version"


class VerificationError(RuntimeError):
    pass


def digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def snapshot(path: Path) -> dict:
    """Read a closed database without opening a writable connection."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        schema = db.execute("PRAGMA user_version").fetchone()[0]
        intervals = [dict(row) for row in db.execute("SELECT * FROM intervals ORDER BY id")]
        settings = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings ORDER BY key")}
        columns = [row["name"] for row in db.execute("PRAGMA table_info(intervals)")]
    return {
        "integrity": integrity,
        "schema": schema,
        "intervals": intervals,
        "settings": settings,
        "columns": columns,
        "seconds": sum(row["end"] - row["start"] for row in intervals),
    }


def public_snapshot(data: dict) -> dict:
    """Never expose sampled application identities, paths, or raw intervals."""
    return {
        "schema": data["schema"],
        "integrity_ok": data["integrity"] == ["ok"],
        "interval_count": len(data["intervals"]),
        "settings_count": len(data["settings"]),
        "total_seconds": round(data["seconds"], 6),
        "intervals_sha256": digest(data["intervals"]),
        "settings_sha256": digest(data["settings"]),
    }


def seed_legacy_preferences_and_history(path: Path) -> None:
    """Add explicit synthetic fixtures AFTER verifying real old-EXE capture."""
    settings = {
        "idle_seconds": 600,
        "close_to_tray": False,
        "upgrade_qa_marker": {"source": "synthetic fixture", "text": "升级前偏好", "enabled": True},
    }
    historical_day = datetime.now().date() - timedelta(days=7)
    start = datetime.combine(historical_day, day_time(10)).timestamp()
    with closing(sqlite3.connect(path)) as db, db:
        for key, value in settings.items():
            db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        db.execute(
            "INSERT INTO intervals(start,end,day,hour,state,app_key,app_name,exe_path) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (start, start + 60, historical_day.isoformat(), 10, "active",
             "upgrade-fixture.exe", "升级验收样本（合成）",
             r"C:\ShiguangUpgradeFixture\upgrade-fixture.exe"),
        )


def launch_and_wait(executable: Path, child_environment: dict, duration_ms: int,
                    timeout_seconds: float, children: list) -> dict:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    launched = time.time()
    process = subprocess.Popen(
        [str(executable), "--background", "--quit-after", str(duration_ms)],
        cwd=str(executable.parent), env=child_environment, startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    children.append(process)
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        # Do not kill by process name, existing PID, or even this timed-out
        # child. Preserve its isolated workspace and report a useful failure.
        raise VerificationError(
            f"Isolated test child PID {process.pid} did not self-exit; no process was terminated."
        ) from error
    exited = time.time()
    return {"exit_code": exit_code, "launched": launched, "exited": exited,
            "wall_seconds": exited - launched}


def verify(args) -> tuple[dict, int]:
    report = {
        "result": "failed",
        "old_version": args.old_version,
        "new_version": args.new_version,
        "scenario": "overwrite one installation; preserve isolated default LOCALAPPDATA data",
        "privacy": "No sampled application names, paths, or raw intervals appear in this report.",
        "checks": {},
    }
    checks = report["checks"]
    children = []
    workspace = None

    def check(name: str, condition: bool):
        checks[name] = bool(condition)
        if not condition:
            raise VerificationError(f"Check failed: {name}")

    try:
        check("running_on_windows", os.name == "nt")
        check("old_package_exists", (args.old_dist / "Shiguang.exe").is_file())
        check("new_package_exists", (args.new_dist / "Shiguang.exe").is_file())
        check("versions_are_distinct", args.old_version != args.new_version)
        check("timing_parameters_valid", args.duration_ms >= 2500 and args.gap_seconds >= 1
              and args.timeout_seconds > args.duration_ms / 1000 + 5)

        args.report.parent.mkdir(parents=True, exist_ok=True)
        qa_root = args.report.parent.resolve()
        workspace = Path(tempfile.mkdtemp(prefix="run-", dir=qa_root)).resolve()
        installation = workspace / "installation"
        local_appdata = workspace / "local-appdata"
        local_appdata.mkdir()
        data_dir = local_appdata / "Shiguang"
        database = data_dir / "usage.sqlite3"
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(local_appdata)
        environment.pop("QT_QPA_PLATFORM", None)

        shutil.copytree(args.old_dist, installation)
        executable = installation / "Shiguang.exe"
        old_run = launch_and_wait(executable, environment, args.duration_ms,
                                  args.timeout_seconds, children)
        report["old_process"] = {"exit_code": old_run["exit_code"],
                                 "wall_seconds": round(old_run["wall_seconds"], 6)}
        check("old_executable_exited_cleanly", old_run["exit_code"] == 0)
        check("default_data_path_created", database.is_file())
        native_capture = snapshot(database)
        report["old_executable_capture"] = public_snapshot(native_capture)
        check("old_database_integrity_ok", native_capture["integrity"] == ["ok"])
        check("old_executable_really_recorded", len(native_capture["intervals"]) > 0
              and native_capture["seconds"] >= 1.0)
        check("old_schema_expected", native_capture["schema"] == args.expected_schema)

        seed_legacy_preferences_and_history(database)
        before = snapshot(database)
        report["before_upgrade"] = public_snapshot(before)
        check("seed_did_not_replace_native_capture",
              all(row in before["intervals"] for row in native_capture["intervals"]))
        backup_files_before = set((data_dir / "backups").glob("*.sqlite3"))
        old_last_end = max(row["end"] for row in before["intervals"])

        # Copy the new release over the exact same directory only after the old
        # child has exited. The data directory is a separate sibling tree.
        shutil.copytree(args.new_dist, installation, dirs_exist_ok=True)
        copied = snapshot(database)
        check("overwriting_installation_did_not_touch_database",
              copied["intervals"] == before["intervals"]
              and copied["settings"] == before["settings"])
        remaining_gap = args.gap_seconds - (time.time() - old_run["exited"])
        if remaining_gap > 0:
            time.sleep(remaining_gap)

        new_run = launch_and_wait(executable, environment, args.duration_ms,
                                  args.timeout_seconds, children)
        report["new_process"] = {"exit_code": new_run["exit_code"],
                                 "wall_seconds": round(new_run["wall_seconds"], 6)}
        check("new_executable_exited_cleanly", new_run["exit_code"] == 0)
        after = snapshot(database)
        report["after_upgrade"] = public_snapshot(after)
        check("new_database_integrity_ok", after["integrity"] == ["ok"])
        check("new_schema_expected", after["schema"] == args.expected_schema)
        check("new_app_version_recorded",
              json.loads(after["settings"].get(APPLICATION_VERSION_KEY, "null")) == args.new_version)

        after_by_id = {row["id"]: row for row in after["intervals"]}
        check("all_old_interval_rows_unchanged", all(
            row["id"] in after_by_id
            and all(after_by_id[row["id"]].get(key) == value for key, value in row.items())
            for row in before["intervals"]
        ))
        ordinary_before = {key: value for key, value in before["settings"].items()
                           if key != APPLICATION_VERSION_KEY}
        check("all_ordinary_settings_preserved", all(
            after["settings"].get(key) == value for key, value in ordinary_before.items()
        ))
        old_ids = {row["id"] for row in before["intervals"]}
        new_rows = [row for row in after["intervals"] if row["id"] not in old_ids]
        new_seconds = sum(row["end"] - row["start"] for row in new_rows)
        check("new_executable_appended_usage", len(new_rows) > 0 and new_seconds >= 1.0)
        check("total_duration_increased_by_new_rows",
              abs(after["seconds"] - before["seconds"] - new_seconds) < 0.0001)
        first_new_start = min(row["start"] for row in new_rows)
        observed_gap = first_new_start - old_last_end
        check("offline_gap_not_counted", first_new_start >= new_run["launched"] - 0.1
              and observed_gap >= args.gap_seconds
              and new_seconds <= new_run["wall_seconds"] + 0.25)
        report["timing"] = {
            "appended_seconds": round(new_seconds, 6),
            "offline_gap_omitted_seconds": round(observed_gap, 6),
            "minimum_requested_gap_seconds": args.gap_seconds,
        }

        backup_files = sorted(set((data_dir / "backups").glob("*.sqlite3")) - backup_files_before)
        check("automatic_upgrade_backup_created", len(backup_files) >= 1)
        backups = [(path, snapshot(path)) for path in backup_files]
        check("every_new_backup_integrity_ok", all(data["integrity"] == ["ok"] for _, data in backups))
        matching = [(path, data) for path, data in backups
                    if data["intervals"] == before["intervals"] and data["settings"] == before["settings"]]
        check("backup_has_exact_pre_upgrade_intervals_and_settings", len(matching) >= 1)
        check("backup_preserved_pre_upgrade_version", all(
            data["settings"].get(APPLICATION_VERSION_KEY) == before["settings"].get(APPLICATION_VERSION_KEY)
            for _, data in matching
        ))
        report["backups"] = [{"name": path.name, **public_snapshot(data)} for path, data in backups]
        log_text = (data_dir / "app.log").read_text(encoding="utf-8", errors="replace")
        check("no_errors_in_isolated_app_log", re.search(r"\b(?:ERROR|CRITICAL)\b", log_text) is None)
        report["result"] = "passed"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        # A stack trace without raw DB rows is helpful for fixing the verifier.
        if not isinstance(error, VerificationError):
            report["error"]["traceback"] = traceback.format_exc()
    finally:
        live_children = [process.pid for process in children if process.poll() is None]
        if live_children:
            report["isolated_test_processes_still_running"] = live_children
            report["temporary_workspace_preserved"] = str(workspace)
            report["temporary_workspace_removed"] = False
        elif workspace is not None:
            # Before recursive removal, verify the resolved target is exactly a
            # generated child of the designated QA directory, never a package.
            resolved = workspace.resolve()
            permitted_parent = args.report.parent.resolve()
            if resolved.parent == permitted_parent and resolved.name.startswith("run-") and not workspace.is_symlink():
                try:
                    shutil.rmtree(resolved)
                    report["temporary_workspace_removed"] = True
                except OSError as error:
                    report["temporary_workspace_removed"] = False
                    report["cleanup_error"] = str(error)
                    report["result"] = "failed"
            else:
                report["temporary_workspace_removed"] = False
                report["cleanup_error"] = "Refused cleanup outside the generated QA workspace."
                report["result"] = "failed"
    return report, 0 if report["result"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-dist", type=Path, default=ROOT / "dist/1.0.2/Shiguang")
    parser.add_argument("--new-dist", type=Path, default=ROOT / f"dist/{CURRENT_VERSION}/Shiguang")
    parser.add_argument("--old-version", default="1.0.2")
    parser.add_argument("--new-version", default=CURRENT_VERSION)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/upgrade/report.json")
    parser.add_argument("--expected-schema", type=int, default=1)
    parser.add_argument("--duration-ms", type=int, default=3500)
    parser.add_argument("--gap-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    args.old_dist = args.old_dist.resolve()
    args.new_dist = args.new_dist.resolve()
    args.report = args.report.resolve()
    report, code = verify(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "passed_checks": sum(report["checks"].values()),
                      "report": str(args.report)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
