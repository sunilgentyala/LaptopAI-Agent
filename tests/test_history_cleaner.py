import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.privacy import history_cleaner as hc
from src.security.audit import AuditLogger


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Every test's audit entries go to a throwaway log, never the real
    project audit.jsonl chain (which live MCP server processes also write
    to)."""
    monkeypatch.setattr(hc, "get_audit", lambda: AuditLogger(str(tmp_path / "test_audit.jsonl")))


def _make_chromium_db(path: Path, n_urls: int = 3) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER);
        CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);
        CREATE TABLE visit_source(id INTEGER PRIMARY KEY, source INTEGER);
        CREATE TABLE keyword_search_terms(keyword_id INTEGER, url_id INTEGER, term TEXT);
        CREATE TABLE segments(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE segment_usage(id INTEGER PRIMARY KEY, segment_id INTEGER);
        CREATE TABLE downloads(id INTEGER PRIMARY KEY, target_path TEXT);
        """
    )
    for i in range(n_urls):
        conn.execute("INSERT INTO urls VALUES (?, ?, ?, ?)", (i, f"https://example.com/{i}", f"Page {i}", 1))
        conn.execute("INSERT INTO visits VALUES (?, ?, ?)", (i, i, 1))
    conn.execute("INSERT INTO downloads VALUES (1, 'C:/Downloads/file.zip')")
    conn.commit()
    conn.close()


def _make_firefox_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, foreign_count INTEGER DEFAULT 0,
                                 visit_count INTEGER DEFAULT 0, last_visit_date INTEGER);
        CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER);
        CREATE TABLE moz_bookmarks(id INTEGER PRIMARY KEY, fk INTEGER);
        """
    )
    # place 1: bookmarked (should survive, visit stats reset)
    conn.execute("INSERT INTO moz_places VALUES (1, 'https://kept.example', 1, 5, 12345)")
    conn.execute("INSERT INTO moz_bookmarks VALUES (1, 1)")
    # place 2: plain history (should be deleted)
    conn.execute("INSERT INTO moz_places VALUES (2, 'https://gone.example', 0, 2, 12345)")
    conn.execute("INSERT INTO moz_historyvisits VALUES (1, 1, 111)")
    conn.execute("INSERT INTO moz_historyvisits VALUES (2, 2, 222)")
    conn.commit()
    conn.close()


def test_snapshot_sqlite_produces_readable_consistent_copy(tmp_path):
    src = tmp_path / "History"
    _make_chromium_db(src, n_urls=5)
    dst = tmp_path / "backup" / "History.sqlite"

    hc.snapshot_sqlite(src, dst)

    assert dst.exists()
    conn = sqlite3.connect(str(dst))
    assert conn.execute("SELECT count(*) FROM urls").fetchone()[0] == 5
    conn.close()


def test_snapshot_sqlite_times_out_instead_of_hanging_when_locked(tmp_path):
    """Regression test: sqlite3's backup() retries SQLITE_BUSY/LOCKED with no
    built-in cap. Without the watchdog in snapshot_sqlite, this reproduces a
    real hang against a file another connection holds exclusively locked —
    exactly the TOCTOU window between the running-process check and the
    backup call. Must fail fast instead of hanging."""
    src = tmp_path / "History"
    _make_chromium_db(src)

    blocker = sqlite3.connect(str(src))
    blocker.execute("BEGIN EXCLUSIVE")  # blocks even other read-only connections
    blocker.execute("INSERT INTO urls VALUES (999, 'https://blocker.example', 'x', 1)")

    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            hc.snapshot_sqlite(src, tmp_path / "backup.sqlite", timeout=1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 10, f"snapshot_sqlite should fail fast on a locked db, took {elapsed}s"
    finally:
        blocker.rollback()
        blocker.close()


def test_clear_history_db_chromium_wipes_history_keeps_downloads(tmp_path):
    db = tmp_path / "History"
    _make_chromium_db(db)

    hc.clear_history_db(db, "chromium")

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT count(*) FROM urls").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM visits").fetchone()[0] == 0
    # downloads table isn't in the clear list — untouched
    assert conn.execute("SELECT count(*) FROM downloads").fetchone()[0] == 1
    conn.close()


def test_clear_history_db_chromium_tolerates_missing_tables(tmp_path):
    db = tmp_path / "History"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE urls(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    hc.clear_history_db(db, "chromium")  # visits/etc. missing — must not raise


def test_clear_history_db_firefox_preserves_bookmarked_place(tmp_path):
    db = tmp_path / "places.sqlite"
    _make_firefox_db(db)

    hc.clear_history_db(db, "firefox")

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT count(*) FROM moz_historyvisits").fetchone()[0] == 0
    remaining = conn.execute("SELECT id, visit_count, last_visit_date FROM moz_places").fetchall()
    assert remaining == [(1, 0, None)]
    conn.close()


def test_discover_profiles_finds_only_existing_dbs(tmp_path):
    chrome_root = tmp_path / "Chrome"
    (chrome_root / "Default").mkdir(parents=True)
    (chrome_root / "Default" / "History").write_bytes(b"")
    (chrome_root / "Profile 1").mkdir(parents=True)
    # Profile 1 has no History file yet — should be skipped
    (chrome_root / "Guest Profile").mkdir(parents=True)
    (chrome_root / "Guest Profile" / "History").write_bytes(b"")

    spec = hc.BrowserSpec("chrome", "Google Chrome", "chromium", ("chrome.exe",),
                           user_data_root=chrome_root)
    targets = hc.discover_profiles((spec,))

    assert [t.profile_name for t in targets] == ["Default"]


def test_run_skips_running_browser_without_touching_it(tmp_path, monkeypatch):
    root = tmp_path / "Chrome"
    (root / "Default").mkdir(parents=True)
    db = root / "Default" / "History"
    _make_chromium_db(db)
    before = db.read_bytes()

    spec = hc.BrowserSpec("chrome", "Google Chrome", "chromium", ("chrome.exe",), user_data_root=root)
    monkeypatch.setattr(hc, "BROWSERS", (spec,))
    monkeypatch.setattr(hc, "is_browser_running", lambda s: True)

    summary = hc.run(dry_run=False, backup_root=tmp_path / "backups")

    assert db.read_bytes() == before  # untouched
    [result] = summary["results"]
    assert result["skipped_reason"] == "browser_running"
    assert result["backed_up"] is False
    assert result["cleared"] is False


def test_run_backs_up_then_clears_closed_browser(tmp_path, monkeypatch):
    root = tmp_path / "Chrome"
    (root / "Default").mkdir(parents=True)
    db = root / "Default" / "History"
    _make_chromium_db(db, n_urls=4)

    spec = hc.BrowserSpec("chrome", "Google Chrome", "chromium", ("chrome.exe",), user_data_root=root)
    monkeypatch.setattr(hc, "BROWSERS", (spec,))
    monkeypatch.setattr(hc, "is_browser_running", lambda s: False)

    backup_root = tmp_path / "backups"
    summary = hc.run(dry_run=False, backup_root=backup_root)

    [result] = summary["results"]
    assert result["backed_up"] is True
    assert result["cleared"] is True
    assert result["error"] is None

    # backup preserves the original data
    backup_conn = sqlite3.connect(result["backup_path"])
    assert backup_conn.execute("SELECT count(*) FROM urls").fetchone()[0] == 4
    backup_conn.close()

    # live db is actually cleared
    live_conn = sqlite3.connect(str(db))
    assert live_conn.execute("SELECT count(*) FROM urls").fetchone()[0] == 0
    live_conn.close()


def test_run_dry_run_changes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "Chrome"
    (root / "Default").mkdir(parents=True)
    db = root / "Default" / "History"
    _make_chromium_db(db)
    before = db.read_bytes()

    spec = hc.BrowserSpec("chrome", "Google Chrome", "chromium", ("chrome.exe",), user_data_root=root)
    monkeypatch.setattr(hc, "BROWSERS", (spec,))
    monkeypatch.setattr(hc, "is_browser_running", lambda s: False)

    backup_root = tmp_path / "backups"
    summary = hc.run(dry_run=True, backup_root=backup_root)

    assert db.read_bytes() == before
    assert not backup_root.exists()
    [result] = summary["results"]
    assert result["skipped_reason"] == "dry_run"


def test_prune_old_backups_removes_only_expired_runs(tmp_path):
    old_run = tmp_path / (datetime.now() - timedelta(days=200)).strftime(hc.RUN_ID_FORMAT)
    recent_run = tmp_path / (datetime.now() - timedelta(days=5)).strftime(hc.RUN_ID_FORMAT)
    not_a_run = tmp_path / "not-a-timestamp"
    old_run.mkdir()
    recent_run.mkdir()
    not_a_run.mkdir()

    removed = hc.prune_old_backups(tmp_path, retention_days=180)

    assert removed == [old_run.name]
    assert not old_run.exists()
    assert recent_run.exists()
    assert not_a_run.exists()
