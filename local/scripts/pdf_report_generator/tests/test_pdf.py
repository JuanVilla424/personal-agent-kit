"""Coverage for pdf_report_generator (generator.py + main.py). generator.py is loaded
by path (unique name); main.py's `from generator import build_pdf` is faked in sys.modules."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("reportlab")

PDF_DIR = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PDF_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PDF_DIR.parent / "notify"))
    spec.loader.exec_module(mod)
    return mod


class TestPdfGenerator:
    def test_sanitize_strips_emoji(self):
        gen = _load("pdf_generator_ut", "generator.py")
        out = gen._sanitize("héllo 😀 wörld")
        assert "😀" not in out and "héllo" in out

    def test_detect_risk_levels(self):
        gen = _load("pdf_generator_ut", "generator.py")
        assert gen._detect_risk("CRÍTICO algo") == "CRÍTICO"
        assert gen._detect_risk("hay RIESGO") == "RIESGO"
        assert gen._detect_risk("PARCIAL") == "PARCIAL"
        assert gen._detect_risk("INTERVENIDO") == "INTERVENIDO"
        assert gen._detect_risk("OK") == "OK"
        assert gen._detect_risk("todo OK") == "OK"
        assert gen._detect_risk("normal") is None

    def test_col_widths_from_spec(self):
        gen = _load("pdf_generator_ut", "generator.py")
        assert gen._col_widths_from_spec({}, 500) is None
        assert gen._col_widths_from_spec({"column_widths": [0, 0]}, 500) is None
        assert len(gen._col_widths_from_spec({"column_widths": [10, 20]}, 500)) == 2

    def test_build_pdf_full(self, tmp_path):
        gen = _load("pdf_generator_ut", "generator.py")
        spec = {
            "title": "T",
            "sheets": [
                {
                    "column_widths": [10, 20, 30],
                    "sections": [
                        {"type": "title", "text": "Título 😀"},
                        {"type": "subtitle", "text": "Sub"},
                        {"type": "section_title", "text": "Sec"},
                        {
                            "type": "table",
                            "headers": ["A", "Estado"],
                            "rows": [["x", "CRÍTICO"], ["y", "OK"]],
                        },
                        {"type": "kv", "pairs": [["k", "v"]]},
                        {"type": "blank"},
                    ],
                },
                {"sections": [{"type": "table", "headers": ["X"], "rows": [["1"]]}]},
            ],
        }
        assert gen.build_pdf(spec, tmp_path / "r.pdf").exists()

    def test_build_pdf_portrait_empty(self, tmp_path):
        gen = _load("pdf_generator_ut", "generator.py")
        assert gen.build_pdf({"sheets": []}, tmp_path / "p.pdf", orientation="portrait").exists()


class TestPdfMain:
    def _fake(self, monkeypatch):
        fake = types.ModuleType("generator")
        fake.build_pdf = lambda s, o, orientation="landscape": (
            Path(o).write_bytes(b"pdf"),
            Path(o),
        )[1]
        monkeypatch.setitem(sys.modules, "generator", fake)

    def test_main_generates(self, monkeypatch, tmp_path):
        m = _load("pdf_main_ut", "main.py")
        self._fake(monkeypatch)
        monkeypatch.setattr(m, "metrics_push", MagicMock())
        spec_file = tmp_path / "s.json"
        spec_file.write_text('{"sheets": []}')
        monkeypatch.setattr(
            m.sys, "argv", ["main.py", str(spec_file), "--output", str(tmp_path / "r.pdf")]
        )
        m.main()
        assert (tmp_path / "r.pdf").exists()

    def test_main_missing_spec(self, monkeypatch, tmp_path):
        m = _load("pdf_main_ut", "main.py")
        monkeypatch.setattr(m.sys, "argv", ["main.py", str(tmp_path / "no.json")])
        with pytest.raises(SystemExit):
            m.main()


def _fake_build(_spec, out_path, **_kwargs):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"report")
    return out_path


FAKE_GENERATOR = types.SimpleNamespace(build_pdf=_fake_build)


class TestMainOutputAndMirror:
    """The report is the deliverable: a mirror that fails must never lose it."""

    def _run(self, monkeypatch, tmp_path, extra_argv=()):
        m = _load("pdf_main_ut", "main.py")
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
        assert f"monthly.pdf" in capsys.readouterr().out

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
        assert (mirror / "monthly.pdf").exists()
