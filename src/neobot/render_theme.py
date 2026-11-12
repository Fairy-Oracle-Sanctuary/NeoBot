"""生成图共用的浅色样式。

HTML 模板用 ``templates/theme.css``，Pillow 绘图用这里的常量。
两边的色值要保持一致，新插件不要再各写一套配色。
"""
from __future__ import annotations

import os

PAGE_BG = "#f5f6fa"
CARD_BG = "#ffffff"
BORDER = "#e5e7eb"
ROW_LINE = "#f0f1f4"
TITLE_COLOR = "#2b2f38"
SUBTITLE_COLOR = "#6b7280"
HEADING_COLOR = "#1f4fd1"
BODY_COLOR = "#2b2f38"
COMMAND_COLOR = "#b4441b"
FOOTNOTE_COLOR = "#6b7280"

TITLE_SIZE = 34
SUBTITLE_SIZE = 17
HEADING_SIZE = 21
BODY_SIZE = 16.5
FOOTNOTE_SIZE = 14.5
CARD_RADIUS = 14
CARD_PADDING_Y = 16
CARD_PADDING_X = 22
CARD_GAP = 14

# 逻辑像素放大一倍再截图，手机上看字仍然清楚。
DEVICE_SCALE = 2

FONT_FAMILY = '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", sans-serif'
MONO_FAMILY = '"Noto Sans Mono", ui-monospace, monospace'

# Pillow 用的 RGB，对应上面的十六进制。
PAGE_BG_RGB = (245, 246, 250)
CARD_BG_RGB = (255, 255, 255)
BORDER_RGB = (229, 231, 235)
BODY_RGB = (43, 47, 56)
COMMAND_RGB = (180, 68, 27)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.removeprefix("#")
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def resolve_cjk_font(fallback: str) -> tuple[str, int]:
    """优先用 Noto Sans CJK SC。没有时退回调用方传入的字体。"""
    candidates = (
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", 0),
    )
    for path, index in candidates:
        if os.path.isfile(path):
            return path, index
    return fallback, 0
