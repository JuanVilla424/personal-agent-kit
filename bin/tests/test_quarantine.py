"""bin/quarantine.py — the agent's ONLY way to remove something: a reversible, verified move.

The manifest records the original path, sha256 and size of every file; the move is checked after
the fact (read again and compared). Safety refusals stop whole-tree moves. `prune` is the human's
or a timer's job and never runs without --yes.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))

import quarantine as q  # noqa: E402


@pytest.fixture(autouse=True)
def quarantine_root(tmp_path, monkeypatch):
    root = tmp_path / "quarantine"
    monkeypatch.setenv("QUARANTINE_ROOT", str(root))
    return root


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _manifests(root: Path) -> list[dict]:
    out = []
    for batch in sorted(root.iterdir()):
        manifest = batch / "manifest.json"
        if manifest.is_file():
            out.append(json.loads(manifest.read_text()))
    return out


def test_the_default_root_belongs_to_the_kit_and_to_whoever_runs_it(monkeypatch):
    monkeypatch.delenv("QUARANTINE_ROOT")
    assert q._root() == Path.home() / ".pak" / "quarantine"


def test_mv_file_moves_verifies_and_records(quarantine_root, tmp_path):
    src = tmp_path / "scratch.txt"
    src.write_text("scratch data", encoding="utf-8")
    expected = _sha256(src)

    assert q.main(["mv", str(src)]) == 0
    assert not src.exists()

    (manifest,) = _manifests(quarantine_root)
    (entry,) = manifest["entries"]
    assert entry["original"] == str(src)
    assert entry["type"] == "file"
    assert entry["verified"] is True
    assert entry["files"][0]["sha256"] == expected
    assert Path(entry["quarantined"]).read_text(encoding="utf-8") == "scratch data"
    assert oct(quarantine_root.stat().st_mode)[-3:] == "700"


def test_mv_dir_hashes_every_file(quarantine_root, tmp_path):
    tree = tmp_path / "draft"
    (tree / "sub").mkdir(parents=True)
    (tree / "a.txt").write_text("a", encoding="utf-8")
    (tree / "sub" / "b.txt").write_text("b", encoding="utf-8")

    assert q.main(["mv", str(tree)]) == 0
    assert not tree.exists()

    (manifest,) = _manifests(quarantine_root)
    (entry,) = manifest["entries"]
    assert entry["type"] == "dir"
    assert entry["verified"] is True
    assert {f["rel"] for f in entry["files"]} == {"a.txt", "sub/b.txt"}


def test_mv_a_symlink_moves_the_link_not_its_target(quarantine_root, tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("kept", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert q.main(["mv", str(link)]) == 0
    assert target.read_text(encoding="utf-8") == "kept"
    assert _manifests(quarantine_root)[0]["entries"][0]["type"] == "symlink"


def test_mv_same_basename_collision_gets_suffix(quarantine_root, tmp_path):
    one = tmp_path / "one" / "notes.md"
    two = tmp_path / "two" / "notes.md"
    one.parent.mkdir()
    two.parent.mkdir()
    one.write_text("1", encoding="utf-8")
    two.write_text("2", encoding="utf-8")

    assert q.main(["mv", str(one), str(two)]) == 0
    (manifest,) = _manifests(quarantine_root)
    names = sorted(Path(e["quarantined"]).name for e in manifest["entries"])
    assert names == ["notes.md", "notes.md--2"]


def test_two_batches_in_the_same_second_do_not_collide(quarantine_root, tmp_path, monkeypatch):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    assert q.main(["mv", str(first)]) == 0
    batch = next(quarantine_root.iterdir()).name
    monkeypatch.setattr(q, "_batch_dir", lambda root, _id, real=q._batch_dir: real(root, batch))
    assert q.main(["mv", str(second)]) == 0
    assert sorted(p.name for p in quarantine_root.iterdir()) == [batch, f"{batch}-2"]


def test_mv_missing_path_fails_clean(quarantine_root, tmp_path):
    assert q.main(["mv", str(tmp_path / "missing.txt")]) == 3
    assert _manifests(quarantine_root) == []


@pytest.mark.parametrize(
    "dangerous",
    ["/", "/etc", "/usr", "/tmp", str(Path("~").expanduser()), str(Path("~").expanduser().parent)],
)
def test_mv_refuses_whole_trees(quarantine_root, dangerous):
    assert q.main(["mv", dangerous]) == 2
    assert _manifests(quarantine_root) == []


def test_mv_refuses_the_quarantine_root_itself(quarantine_root):
    quarantine_root.mkdir(parents=True)
    assert q.main(["mv", str(quarantine_root)]) == 2


def test_a_failed_verification_is_reported_and_exits_4(quarantine_root, tmp_path, monkeypatch):
    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")
    hashes = iter(["before", "after"])
    monkeypatch.setattr(q, "_sha256", lambda _p: next(hashes))
    assert q.main(["mv", str(src)]) == 4
    assert _manifests(quarantine_root)[0]["entries"][0]["verified"] is False


def test_show_lists_batches(quarantine_root, tmp_path, capsys):
    assert q.main(["show"]) == 0
    assert "nothing quarantined yet" in capsys.readouterr().out
    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")
    assert q.main(["mv", str(src)]) == 0
    (quarantine_root / "stray").mkdir()
    assert q.main(["show"]) == 0
    listed = capsys.readouterr().out
    assert "1 entries" in listed and "stray  (no manifest)" in listed

    (manifest,) = _manifests(quarantine_root)
    assert q.main(["show", manifest["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == manifest["id"]
    assert q.main(["show", "no-such-batch"]) == 3


def test_prune_needs_yes_and_then_drops_only_old_batches(quarantine_root, tmp_path, capsys):
    assert q.main(["prune", "--days", "30", "--yes"]) == 0
    assert "nothing to prune" in capsys.readouterr().out
    src = tmp_path / "old.txt"
    src.write_text("old", encoding="utf-8")
    assert q.main(["mv", str(src)]) == 0
    (manifest,) = _manifests(quarantine_root)
    batch = quarantine_root / manifest["id"]

    old = time.time() - 40 * q.SECONDS_PER_DAY
    os.utime(batch, (old, old))

    assert q.main(["prune", "--days", "30"]) == 2  # no --yes: refuses
    assert batch.exists()
    assert q.main(["prune", "--days", "30", "--yes"]) == 0
    assert not batch.exists()
