"""Coverage for excel_report_generator (generator.py + main.py).

generator.py is loaded by path (unique module name) because both report tools ship a
module literally named 'generator'. main.py's `from generator import build_excel` is
satisfied by injecting a fake into sys.modules.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("openpyxl")

EXCEL_DIR = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, EXCEL_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(EXCEL_DIR.parent / "notify"))  # for `from ops import metrics_push`
    spec.loader.exec_module(mod)
    return mod


class TestGenerator:
    def test_build_excel_all_sections(self, tmp_path):
        gen = _load("excel_generator_ut", "generator.py")
        spec = {
            "sheets": [
                {
                    "name": "S1",
                    "column_widths": [10, 20, 30],
                    "sections": [
                        {"type": "title", "text": "T"},
                        {"type": "subtitle", "text": "Sub"},
                        {"type": "section_title", "text": "Sec"},
                        {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"], ["3", "4"]]},
                        {"type": "kv", "pairs": [["k", "v"], ["k2", "v2"]]},
                        {"type": "blank"},
                        {"type": "unknown_ignored"},
                    ],
                }
            ]
        }
        out = tmp_path / "r.xlsx"
        assert gen.build_excel(spec, out).exists()

    def test_build_excel_default_widths(self, tmp_path):
        gen = _load("excel_generator_ut", "generator.py")
        spec = {
            "sheets": [
                {"name": "S", "sections": [{"type": "table", "headers": [], "rows": [["x"]]}]}
            ]
        }
        assert gen.build_excel(spec, tmp_path / "r2.xlsx").exists()


class TestMain:
    def _fake_generator(self, monkeypatch):
        fake = types.ModuleType("generator")
        fake.build_excel = lambda s, o: (Path(o).write_bytes(b"xlsx-bytes"), Path(o))[1]
        monkeypatch.setitem(sys.modules, "generator", fake)

    def test_main_generates(self, monkeypatch, tmp_path):
        m = _load("excel_main_ut", "main.py")
        self._fake_generator(monkeypatch)
        monkeypatch.setattr(m, "metrics_push", MagicMock())
        spec_file = tmp_path / "spec.json"
        spec_file.write_text('{"filename_base": "rep", "sheets": []}')
        monkeypatch.setattr(
            m.sys, "argv", ["main.py", str(spec_file), "--output", str(tmp_path / "r.xlsx")]
        )
        m.main()
        assert (tmp_path / "r.xlsx").exists()

    def test_main_mirror_copy(self, monkeypatch, tmp_path):
        m = _load("excel_main_ut", "main.py")
        self._fake_generator(monkeypatch)
        monkeypatch.setattr(m, "metrics_push", MagicMock())
        monkeypatch.setattr(m, "MIRROR_DIR", str(tmp_path / "mirror"))
        (tmp_path / "mirror").mkdir()
        spec_file = tmp_path / "spec.json"
        spec_file.write_text('{"sheets": []}')
        monkeypatch.setattr(
            m.sys, "argv", ["main.py", str(spec_file), "--output", str(tmp_path / "r.xlsx")]
        )
        m.main()
        assert (tmp_path / "mirror" / "r.xlsx").exists()

    def test_main_missing_spec_exits(self, monkeypatch, tmp_path):
        m = _load("excel_main_ut", "main.py")
        monkeypatch.setattr(m.sys, "argv", ["main.py", str(tmp_path / "nope.json")])
        with pytest.raises(SystemExit):
            m.main()


def _fake_build(_spec, out_path, **_kwargs):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"report")
    return out_path


FAKE_GENERATOR = types.SimpleNamespace(build_excel=_fake_build)


class TestMainOutputAndMirror:
    """The report is the deliverable: a mirror that fails must never lose it."""

    def _run(self, monkeypatch, tmp_path, extra_argv=()):
        m = _load("excel_main_ut", "main.py")
        monkeypatch.setitem(sys.modules, "generator", FAKE_GENERATOR)
        monkeypatch.setattr(m.metrics_push, "push_run", MagicMock())
        monkeypatch.setattr(m, "OUTPUT_DIR", tmp_path / "out")
        spec_file = tmp_path / "spec.json"
        spec_file.write_text('{"filename_base": "monthly"}', encoding="utf-8")
        monkeypatch.setattr(m.sys, "argv", ["main.py", str(spec_file), *extra_argv])
        return m

    def test_default_output_uses_filename_base(self, monkeypatch, tmp_path, capsys):
        m = self._run(monkeypatch, tmp_path)
        monkeypatch.setattr(m, "MIRROR_DIR", "")
        m.main()
        assert f"monthly.xlsx" in capsys.readouterr().out

    def test_mirror_without_permission_keeps_the_report(self, monkeypatch, tmp_path, capsys):
        m = self._run(monkeypatch, tmp_path)
        monkeypatch.setattr(m, "MIRROR_DIR", str(tmp_path / "mirror"))
        monkeypatch.setattr(m.shutil, "copy2", MagicMock(side_effect=PermissionError("no")))
        m.main()
        captured = capsys.readouterr()
        assert "No write permission" in captured.err
        assert "generated" in captured.out

    def test_mirror_failure_keeps_the_report(self, monkeypatch, tmp_path, capsys):
        m = self._run(monkeypatch, tmp_path)
        monkeypatch.setattr(m, "MIRROR_DIR", str(tmp_path / "mirror"))
        monkeypatch.setattr(m.shutil, "copy2", MagicMock(side_effect=OSError("disk full")))
        m.main()
        captured = capsys.readouterr()
        assert "Could not copy" in captured.err
        assert "generated" in captured.out

    def test_mirror_copy_lands_in_the_mirror_dir(self, monkeypatch, tmp_path, capsys):
        m = self._run(monkeypatch, tmp_path)
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        monkeypatch.setattr(m, "MIRROR_DIR", str(mirror))
        m.main()
        assert "Copied to" in capsys.readouterr().out
        assert (mirror / "monthly.xlsx").exists()
