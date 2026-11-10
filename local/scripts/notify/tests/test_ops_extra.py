"""Coverage for ops/backup_restore.py and ops/watchdog.py."""

import sys
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops import backup_restore as br  # noqa: E402
from ops import watchdog as wd  # noqa: E402


class TestBackupRestore:
    def test_targets(self):
        assert len(br._targets()) == 4

    def test_backup_local(self, monkeypatch, tmp_path):
        notify_dir = tmp_path / "notify"
        (notify_dir / "data").mkdir(parents=True)
        monkeypatch.setattr(br, "_NOTIFY_DIR", notify_dir)
        monkeypatch.setattr(br, "_BACKUP_DIR", tmp_path / "backups")
        monkeypatch.setattr(br, "_S3_BUCKET", "")
        br.backup()
        assert list((tmp_path / "backups").glob("*.tar.gz"))

    def test_backup_with_s3(self, monkeypatch, tmp_path):
        notify_dir = tmp_path / "n"
        notify_dir.mkdir()
        monkeypatch.setattr(br, "_NOTIFY_DIR", notify_dir)
        monkeypatch.setattr(br, "_BACKUP_DIR", tmp_path / "b")
        monkeypatch.setattr(br, "_S3_BUCKET", "mybucket")
        monkeypatch.setattr(br.subprocess, "run", MagicMock())
        br.backup()

    def test_backup_s3_failure_swallowed(self, monkeypatch, tmp_path):
        notify_dir = tmp_path / "n"
        notify_dir.mkdir()
        monkeypatch.setattr(br, "_NOTIFY_DIR", notify_dir)
        monkeypatch.setattr(br, "_BACKUP_DIR", tmp_path / "b")
        monkeypatch.setattr(br, "_S3_BUCKET", "mybucket")
        monkeypatch.setattr(br.subprocess, "run", MagicMock(side_effect=OSError("down")))
        br.backup()

    def test_restore(self, monkeypatch, tmp_path):
        monkeypatch.setattr(br, "_NOTIFY_DIR", tmp_path / "n")
        (tmp_path / "n").mkdir()
        arch = tmp_path / "a.tar.gz"
        member = tmp_path / "x.txt"
        member.write_text("hi")
        with tarfile.open(arch, "w:gz") as tar:
            tar.add(member, arcname="x.txt")
        br.restore(str(arch))
        assert (tmp_path / "n" / "restore_tmp" / "x.txt").exists()

    def test_restore_missing(self):
        with pytest.raises(FileNotFoundError):
            br.restore("/nonexistent.tar.gz")


class TestWatchdog:
    def test_load_default_and_save(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wd, "_STATE_FILE", tmp_path / "data" / "w.state")
        assert wd._load_state()["active_color"] == "blue"
        wd._save_state({"crashes": [], "active_color": "green", "last_swap": 1})
        assert wd._load_state()["active_color"] == "green"

    def test_load_corrupt_falls_back(self, monkeypatch, tmp_path):
        f = tmp_path / "w.state"
        f.write_text("not json")
        monkeypatch.setattr(wd, "_STATE_FILE", f)
        assert wd._load_state()["active_color"] == "blue"

    def test_active_color_found(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: MagicMock(stdout="active\n"))
        assert wd._active_color() == "blue"

    def test_active_color_default(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: MagicMock(stdout="inactive"))
        assert wd._active_color() == "blue"

    def test_active_color_exception(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", MagicMock(side_effect=OSError("x")))
        assert wd._active_color() == "blue"

    def test_restart_count(self, monkeypatch):
        monkeypatch.setattr(
            wd.subprocess,
            "run",
            lambda *a, **k: MagicMock(
                stdout="Started Personal Agent Kit\nStarted Personal Agent Kit\n"
            ),
        )
        assert wd._restart_count("blue", 300) == 2

    def test_restart_count_error(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", MagicMock(side_effect=OSError("x")))
        assert wd._restart_count("blue", 300) == 0

    def test_swap_success(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", MagicMock())
        monkeypatch.setattr(wd.time, "sleep", lambda s: None)
        assert wd._swap("blue", "green") is True

    def test_swap_failure(self, monkeypatch):
        monkeypatch.setattr(wd.subprocess, "run", MagicMock(side_effect=OSError("x")))
        assert wd._swap("blue", "green") is False

    def test_run_no_crashes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wd, "_STATE_FILE", tmp_path / "w.state")
        monkeypatch.setattr(wd, "_active_color", lambda: "blue")
        monkeypatch.setattr(wd, "_restart_count", lambda c, w: 0)
        wd.run()

    def test_run_swaps_on_high_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wd, "_STATE_FILE", tmp_path / "w.state")
        monkeypatch.setattr(wd, "_active_color", lambda: "blue")
        monkeypatch.setattr(wd, "_restart_count", lambda c, w: 5)
        monkeypatch.setattr(wd, "_swap", lambda a, i: True)
        wd.run()

    def test_run_swap_failure_alerts(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wd, "_STATE_FILE", tmp_path / "w.state")
        monkeypatch.setattr(wd, "_active_color", lambda: "green")
        monkeypatch.setattr(wd, "_restart_count", lambda c, w: 5)
        monkeypatch.setattr(wd, "_swap", lambda a, i: False)
        wd.run()
