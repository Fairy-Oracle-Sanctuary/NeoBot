"""生成图共用同一套浅色样式。"""
from pathlib import Path

from neobot import render_theme
from neobot.core.managers.image_manager import DEVICE_SCALE

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "neobot" / "templates"
RENDERED = (
    "help.html",
    "status.html",
    "code_execution.html",
    "github_repo.html",
    "weather.html",
    "osu_difficulty.html",
    "maimaidx_b50.html",
)


def test_theme_tokens_match_the_shared_stylesheet():
    css = (TEMPLATES / "theme.css").read_text(encoding="utf-8")
    assert render_theme.PAGE_BG == "#f5f6fa"
    assert render_theme.BORDER == "#e5e7eb"
    assert render_theme.TITLE_COLOR == "#2b2f38"
    assert render_theme.SUBTITLE_COLOR == "#6b7280"
    assert render_theme.HEADING_COLOR == "#1f4fd1"
    assert render_theme.COMMAND_COLOR == "#b4441b"
    assert render_theme.FOOTNOTE_COLOR == "#6b7280"
    assert render_theme.ROW_LINE == "#f0f1f4"
    assert "Noto Sans CJK SC" in css
    for token in (
        render_theme.PAGE_BG,
        render_theme.BORDER,
        render_theme.TITLE_COLOR,
        render_theme.HEADING_COLOR,
        render_theme.COMMAND_COLOR,
        render_theme.ROW_LINE,
    ):
        assert token in css
    assert render_theme.DEVICE_SCALE == 2
    assert DEVICE_SCALE == 2


def test_rendered_templates_include_the_shared_theme():
    for name in RENDERED:
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert 'include "theme.css"' in text
        assert "nb-page" in text
