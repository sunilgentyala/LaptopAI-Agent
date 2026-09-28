"""Backs up and clears browsing history for locally installed browsers.

Runs on a schedule (see scripts/browser_history_cleanup_task.bat, registered
in Task Scheduler to fire every 15 days) or on demand via
`python main.py clean-browser-history` / the MCP `browser_history_cleanup`
tool.

Safety model: a browser is either fully "closed" or fully "skipped" for a
given run — never partially touched. Chromium browsers open their History
sqlite file in exclusive locking mode for as long as the browser process is
alive, so any external connection attempt (even read-only) fails outright
while it's running; a plain file copy would still succeed but could capture
a torn, mid-transaction snapshot (Chrome's History-journal sidecar file is
the tell). Rather than rely on that, if the browser process is running we
skip it entirely for this run (no backup, no clear) and report why. Only a
closed browser gets backed up (via SQLite's own backup API, which produces a
consistent snapshot) and then cleared.

This module never terminates a running browser itself.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import yaml

from src.security.audit import get_audit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BACKUP_ROOT = Path.home() / "Documents" / "BrowserHistoryBackups"
DEFAULT_RETENTION_DAYS = 180
RUN_ID_FORMAT = "%Y-%m-%d_%H%M%S"
SNAPSHOT_TIMEOUT_SEC = 15.0

_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
_APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    display_name: str
    kind: str  # "chromium" | "firefox"
    process_names: tuple[str, ...]
    user_data_root: Path | None = None   # chromium only
    profiles_root: Path | None = None    # firefox only


BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec("chrome", "Google Chrome", "chromium", ("chrome.exe",),
                user_data_root=_LOCALAPPDATA / "Google" / "Chrome" / "User Data"),
    BrowserSpec("edge", "Microsoft Edge", "chromium", ("msedge.exe",),
                user_data_root=_LOCALAPPDATA / "Microsoft" / "Edge" / "User Data"),
    BrowserSpec("brave", "Brave", "chromium", ("brave.exe",),
                user_data_root=_LOCALAPPDATA / "BraveSoftware" / "Brave-Browser" / "User Data"),
    BrowserSpec("firefox", "Mozilla Firefox", "firefox", ("firefox.exe",),
                profiles_root=_APPDATA / "Mozilla" / "Firefox" / "Profiles"),
)

CHROMIUM_CLEAR_STATEMENTS: tuple[str, ...] = (
    "DELETE FROM visits",
    "DELETE FROM visit_source",
    "DELETE FROM urls",
    "DELETE FROM keyword_search_terms",
    "DELETE FROM segment_usage",
    "DELETE FROM segments",
)

# Clears visit history while preserving bookmarked places (and the bookmarks
# themselves), matching what Firefox's own "Clear Recent History > Browsing
# & Download History" does to places.sqlite.
FIREFOX_CLEAR_STATEMENTS: tuple[str, ...] = (
    "DELETE FROM moz_historyvisits",
    """DELETE FROM moz_places
       WHERE foreign_count = 0
         AND id NOT IN (SELECT DISTINCT fk FROM moz_bookmarks WHERE fk IS NOT NULL)""",
    "UPDATE moz_places SET visit_count = 0, last_visit_date = NULL",
)


@dataclass
class ProfileTarget:
    browser_key: str
    browser_name: str
    profile_name: str
    db_path: Path
    kind: str


@dataclass
class ProfileResult:
    browser: str
    profile: str
    running: bool
    backed_up: bool = False
    backup_path: str | None = None
    cleared: bool = False
    error: str | None = None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _config_defaults() -> dict[str, Any]:
    """Read the browser_hygiene: section of config.yaml, if present."""
    cfg_path = REPO_ROOT / "config.yaml"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return cfg.get("browser_hygiene", {}) or {}


def _browser_spec(key: str) -> BrowserSpec:
    for b in BROWSERS:
        if b.key == key:
            return b
    raise KeyError(key)


def discover_profiles(browsers: tuple[BrowserSpec, ...] | None = None) -> list[ProfileTarget]:
    """Find every browser profile on this machine that has a history DB."""
    if browsers is None:
        browsers = BROWSERS  # read fresh, not bound at def time
    targets: list[ProfileTarget] = []
    for b in browsers:
        if b.kind == "chromium":
            root = b.user_data_root
            if not root or not root.exists():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name != "Default" and not entry.name.startswith("Profile "):
                    continue
                db = entry / "History"
                if db.exists():
                    targets.append(ProfileTarget(b.key, b.display_name, entry.name, db, "chromium"))
        elif b.kind == "firefox":
            root = b.profiles_root
            if not root or not root.exists():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir():
                    continue
                db = entry / "places.sqlite"
                if db.exists():
                    targets.append(ProfileTarget(b.key, b.display_name, entry.name, db, "firefox"))
    return targets


def is_browser_running(spec: BrowserSpec) -> bool:
    names = {p.lower() for p in spec.process_names}
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info.get("name") or "").lower() in names:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _sqlite_ro_uri(path: Path) -> str:
    return "file:" + urllib.parse.quote(path.as_posix(), safe="/:") + "?mode=ro"


def snapshot_sqlite(src: Path, dst: Path, timeout: float = SNAPSHOT_TIMEOUT_SEC) -> None:
    """Consistent copy of a closed SQLite DB via SQLite's own backup API.

    Only safe to call once the owning browser process has exited — see
    module docstring for why a live Chromium History file can't be read
    this way (and shouldn't be raw-copied instead).

    sqlite3.Connection.backup() retries SQLITE_BUSY/SQLITE_LOCKED forever
    with no built-in cap — confirmed by hand: calling Connection.interrupt()
    from a threading.Timer does *not* reliably break it out of that C-level
    retry loop. So if the browser is relaunched in the window between the
    running-process check and this call (a real TOCTOU race, not just
    theoretical), the call can hang indefinitely. Instead, run it on a
    daemon thread and simply stop waiting after `timeout` seconds: `join`
    with a timeout is a plain bounded wait, no interrupt semantics needed.
    If the backup thread is still stuck when we give up, it's abandoned —
    being a daemon thread, it won't keep the process alive — and this
    raises TimeoutError so the caller can record a clean failure instead of
    a scheduled 3am run hanging forever.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    outcome: dict[str, Exception] = {}

    def _do_backup() -> None:
        try:
            src_conn = sqlite3.connect(_sqlite_ro_uri(src), uri=True)
            try:
                dst_conn = sqlite3.connect(str(dst))
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
        except Exception as e:  # surfaced on the calling thread below
            outcome["error"] = e

    worker = threading.Thread(target=_do_backup, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        if dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        raise TimeoutError(f"timed out after {timeout}s backing up {src} (still locked?)")
    if "error" in outcome:
        raise outcome["error"]
    if dst.exists() and dst.stat().st_size == 0:
        dst.unlink()  # leftover from a failed backup


def clear_history_db(db_path: Path, kind: str) -> None:
    statements = CHROMIUM_CLEAR_STATEMENTS if kind == "chromium" else FIREFOX_CLEAR_STATEMENTS
    conn = sqlite3.connect(str(db_path))
    try:
        for stmt in statements:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                # Table missing for this schema/browser version — nothing to clear there.
                continue
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()


def prune_old_backups(backup_root: Path, retention_days: int) -> list[str]:
    """Delete run folders older than retention_days. Never touches today's run."""
    removed: list[str] = []
    if not backup_root.exists():
        return removed
    cutoff = datetime.now() - timedelta(days=retention_days)
    for entry in backup_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            stamp = datetime.strptime(entry.name, RUN_ID_FORMAT)
        except ValueError:
            continue
        if stamp < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
    return removed


def run(dry_run: bool = False, backup_root: Path | str | None = None,
        retention_days: int | None = None) -> dict[str, Any]:
    """Back up then clear history for every closed browser profile found.

    A browser that's currently running is left completely untouched (no
    backup, no clear) and reported with skipped_reason="browser_running".
    dry_run=True only reports what would happen; it changes nothing.

    backup_root/retention_days fall back to config.yaml's browser_hygiene:
    section, then to the module defaults, if not given explicitly.
    """
    defaults = _config_defaults()
    backup_root = Path(backup_root or defaults.get("backup_root") or DEFAULT_BACKUP_ROOT)
    if retention_days is None:
        retention_days = int(defaults.get("retention_days", DEFAULT_RETENTION_DAYS))
    run_id = datetime.now().strftime(RUN_ID_FORMAT)
    run_dir = backup_root / run_id
    audit = get_audit()

    results: list[ProfileResult] = []
    for target in discover_profiles():
        spec = _browser_spec(target.browser_key)
        running = is_browser_running(spec)
        result = ProfileResult(target.browser_name, target.profile_name, running)

        if running:
            result.skipped_reason = "browser_running"
            results.append(result)
            if not dry_run:
                audit.log("BROWSER_HYGIENE", "history_cleaner", "skipped",
                           str(target.db_path), "browser running")
            continue

        if dry_run:
            result.skipped_reason = "dry_run"
            results.append(result)
            continue

        backup_dst = run_dir / target.browser_key / f"{target.profile_name}.sqlite"
        try:
            snapshot_sqlite(target.db_path, backup_dst)
            result.backed_up = True
            result.backup_path = str(backup_dst)
        except Exception as e:
            result.error = f"backup failed: {e}"
            if backup_dst.exists():
                backup_dst.unlink()  # don't leave a partial/corrupt snapshot behind
            audit.log("BROWSER_HYGIENE", "history_cleaner", "backup_failed",
                       str(target.db_path), str(e))
            results.append(result)
            continue

        try:
            clear_history_db(target.db_path, target.kind)
            result.cleared = True
            audit.log("BROWSER_HYGIENE", "history_cleaner", "cleared",
                       str(target.db_path), f"backup={backup_dst}")
        except Exception as e:
            result.error = f"clear failed: {e}"
            audit.log("BROWSER_HYGIENE", "history_cleaner", "clear_failed",
                       str(target.db_path), str(e))
        results.append(result)

    pruned = [] if dry_run else prune_old_backups(backup_root, retention_days)

    summary = {
        "run_id": run_id,
        "dry_run": dry_run,
        "backup_root": str(backup_root),
        "results": [r.to_dict() for r in results],
        "pruned_backups": pruned,
    }
    if not dry_run:
        audit.log("BROWSER_HYGIENE", "history_cleaner", "run_complete", run_id,
                   f"{sum(r.cleared for r in results)} cleared, "
                   f"{sum(r.skipped_reason == 'browser_running' for r in results)} skipped, "
                   f"{sum(bool(r.error) for r in results)} errors")
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"[{summary['run_id']}] browser history cleanup "
          f"({'DRY RUN' if summary['dry_run'] else 'LIVE'})")
    if not summary["results"]:
        print("  No browser profiles found on this machine.")
    for r in summary["results"]:
        status = ("cleared" if r["cleared"] else
                   r["skipped_reason"] if r["skipped_reason"] else
                   "error" if r["error"] else "backed up only")
        line = f"  {r['browser']} / {r['profile']}: {status}"
        if r["backup_path"]:
            line += f" -> {r['backup_path']}"
        if r["error"]:
            line += f" ({r['error']})"
        print(line)
    if summary["pruned_backups"]:
        print(f"  Pruned {len(summary['pruned_backups'])} backup run(s) older than retention window.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would happen without touching anything")
    parser.add_argument("--backup-root", default=None,
                         help=f"Where to store backups (default: {DEFAULT_BACKUP_ROOT})")
    parser.add_argument("--retention-days", type=int, default=None,
                         help=f"Delete backups older than this many days (default: config.yaml, else {DEFAULT_RETENTION_DAYS})")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, backup_root=args.backup_root,
                 retention_days=args.retention_days)
    _print_summary(result)
    sys.exit(1 if any(r["error"] for r in result["results"]) else 0)
