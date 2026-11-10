import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.i18n import detect_locale, t


class TestT:
    def test_known_key_spanish(self):
        assert "Procesando" in t("processing", locale="es")

    def test_known_key_english(self):
        assert "Processing" in t("processing", locale="en")

    def test_unknown_key_returns_key(self):
        assert t("nonexistent_key") == "nonexistent_key"

    def test_default_locale_is_english(self):
        assert t("processing") == t("processing", locale="en")

    def test_format_kwargs_substituted(self):
        result = t("timeout", locale="en", secs=30)
        assert "30s" in result

    def test_format_kwargs_missing_falls_back_gracefully(self):
        result = t("timeout", locale="en")
        assert "{secs}" in result or "secs" in result

    def test_quiet_hours_format(self):
        result = t("quiet_hours", locale="es", start="07:00", end="18:00")
        assert "07:00" in result
        assert "18:00" in result

    def test_content_blocked_with_rule(self):
        result = t("content_blocked", locale="en", rule="XSS")
        assert "XSS" in result

    def test_cost_report_format(self):
        result = t("cost_report", locale="en", cost=1.5678, queries=42)
        assert "1.5678" in result
        assert "42" in result

    def test_progress_tool_format(self):
        result = t("progress_tool", locale="en", tool="Bash")
        assert "Bash" in result

    def test_all_keys_have_spanish(self):
        from core.i18n import _STRINGS

        for key, entry in _STRINGS.items():
            assert "es" in entry, f"Key '{key}' missing Spanish translation"

    def test_all_keys_have_english(self):
        from core.i18n import _STRINGS

        for key, entry in _STRINGS.items():
            assert "en" in entry, f"Key '{key}' missing English translation"


class TestDetectLocale:
    def test_en_hint_returns_en(self):
        assert detect_locale("en") == "en"

    def test_en_us_hint_returns_en(self):
        assert detect_locale("en-US") == "en"

    def test_es_hint_returns_es(self):
        assert detect_locale("es") == "es"

    def test_none_hint_returns_en(self):
        assert detect_locale(None) == "en"

    def test_empty_string_returns_en(self):
        assert detect_locale("") == "en"

    def test_unknown_hint_returns_en(self):
        assert detect_locale("fr") == "en"
