import json
from pathlib import Path

import pytest

import backup
import tempfile
import errno


def fake_mkdtemp(prefix: str | None = None, dir: str | None = None) -> str:
    # Provide sensible defaults when callers pass None to mirror tempfile.mkdtemp
    base_dir = Path(dir) if dir is not None else Path(tempfile.gettempdir())
    prefix_str = prefix or ""
    return str(base_dir / (prefix_str + "TMP"))


def test_create_backup_isolated_success(monkeypatch, fake_mkdtemp_func, fake_mkdir_func, write_text_capture, fake_walk_builder):
    # Fully isolated test: no filesystem operations should run
    # Prevent actual directory creation during manager init
    monkeypatch.setattr(backup.Path, "mkdir", fake_mkdir_func)
    manager = backup.SaveBackupManager("/fake/save_dir", "/fake/backups", max_backups=2)

    # Fake os.walk to report two files in save_dir and in backup destination
    nested = {"a.txt": None, "b.txt": None}
    monkeypatch.setattr(backup.os, "walk", fake_walk_builder(Path("/fake/save_dir"), nested))

    # Fake mkdtemp to return a temp path string inside the fake backup dir
    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp_func)

    # Fake copytree to do nothing
    def fake_copytree(src, dst, **kwargs):
        return dst

    monkeypatch.setattr(backup.shutil, "copytree", fake_copytree)

    # Fake os.replace to simulate atomic rename success
    def fake_replace(a, b):
        return None

    monkeypatch.setattr(backup.os, "replace", fake_replace)

    # Fake checksum and size
    monkeypatch.setattr(backup, "compute_directory_sha256", lambda p: "deadbeef")
    monkeypatch.setattr(backup, "get_directory_size", lambda p: 1234)

    # Capture Path.write_text calls in-memory using fixture
    writes, fake_write_text = write_text_capture
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    # Run create_backup and assert metadata content captured
    res = manager.create_backup("iso-desc")
    assert res is not None
    # metadata path key should exist in writes
    meta_key = str(Path(res) / ".backup_meta.json")
    assert meta_key in writes
    meta = json.loads(writes[meta_key])
    assert meta.get("checksum") == "deadbeef"
    assert meta.get("move_method") == "atomic"


def test_create_backup_isolated_exdev_and_move_called(monkeypatch, fake_mkdtemp_func, fake_mkdir_func, write_text_capture, fake_walk_builder):
    # Isolated test for EXDEV fallback that ensures shutil.move is called
    # Prevent actual directory creation during manager init
    monkeypatch.setattr(backup.Path, "mkdir", fake_mkdir_func)
    manager = backup.SaveBackupManager("/fake/save_dir", "/fake/backups", max_backups=2)

    nested = {"a.txt": None}
    monkeypatch.setattr(backup.os, "walk", fake_walk_builder(Path("/fake/save_dir"), nested))
    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp_func)
    monkeypatch.setattr(backup.shutil, "copytree", lambda src, dst, **kwargs: dst)

    # Make os.replace raise EXDEV
    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(backup.os, "replace", fake_replace)

    # Record calls to shutil.move and simulate success
    move_called = {"called": False, "args": None}

    def fake_move(src, dst, *args, **kwargs):
        move_called["called"] = True
        move_called["args"] = (src, dst)
        return dst

    monkeypatch.setattr(backup.shutil, "move", fake_move)

    monkeypatch.setattr(backup, "compute_directory_sha256", lambda p: "cafebabe")
    monkeypatch.setattr(backup, "get_directory_size", lambda p: 42)

    writes, fake_write_text = write_text_capture
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    res = manager.create_backup("exdev-iso")
    assert res is not None
    assert move_called["called"] is True
    meta_key = str(Path(res) / ".backup_meta.json")
    assert meta_key in writes
    meta = json.loads(writes[meta_key])
    assert meta.get("move_method") == "copied"


def test_default_backup_dir_is_repo_backups(monkeypatch):
    """Ensure SaveBackupManager defaults to the repository/script root 'backups' dir
    when no backup_dir argument is provided.
    """
    recorded = {}

    def record_mkdir(self, mode=0o777, parents=False, exist_ok=False):
        recorded['path'] = str(self)
        # simulate no-op behavior
        return None

    monkeypatch.setattr(backup.Path, "mkdir", record_mkdir)

    # Create manager without providing a backup_dir to trigger default behavior
    manager = backup.SaveBackupManager("/fake/save_dir", None, max_backups=2)

    expected = Path(backup.__file__).parent / "backups"
    assert recorded.get('path') == str(expected)
    assert manager.backup_dir == expected
