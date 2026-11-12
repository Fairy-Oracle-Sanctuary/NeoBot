"""把 /help 拆成总览、分类页和单插件页，避免一张图把全部用法叠在一起。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Iterable, Optional

PAGE_BUDGET_PX = 1200
_PAGE_CHROME_PX = 230
_CARD_BASE_PX = 122
_LINE_PX = 32
_NAME_CHARS_PER_LINE = 26

FALLBACK_CATEGORY = "其他"
CATEGORY_ORDER = ("工具", "娱乐", "群管理", "信息查询", "游戏", "系统", FALLBACK_CATEGORY)

# 没写 category 的已知插件。新插件可以在 define_plugin(category=...) 里自己标明。
_NAME_CATEGORY = {
    "caption": "工具",
    "code_py": "工具",
    "echo": "工具",
    "feedback": "工具",
    "version": "工具",
    "mirror_avatar": "工具",
    "greek_alphabet": "工具",
    "decide": "娱乐",
    "dice": "娱乐",
    "daily": "娱乐",
    "daily_cp": "娱乐",
    "furry": "娱乐",
    "e926_gallery": "娱乐",
    "fursona": "娱乐",
    "fursona_roll": "娱乐",
    "jrcd": "娱乐",
    "thpic": "娱乐",
    "poke_reply": "娱乐",
    "poll": "娱乐",
    "music": "娱乐",
    "reminder": "群管理",
    "birthday": "群管理",
    "chatty": "群管理",
    "group_welcome": "群管理",
    "auto_approve": "群管理",
    "admin": "群管理",
    "broadcast": "群管理",
    "group_manage": "群管理",
    "weather": "信息查询",
    "daily_news": "信息查询",
    "web_parser": "信息查询",
    "image_source": "信息查询",
    "twitter_parser": "信息查询",
    "ehentai_parser": "信息查询",
    "jinman_parser": "信息查询",
    "github_parser": "信息查询",
    "osu_plugin": "游戏",
    "maimaidx": "游戏",
    "mcc": "游戏",
    "bot_status": "系统",
    "帮助": "系统",
}

_KEYWORD_RULES = (
    ("群管理", ("群管", "入群", "管理员", "提醒", "生日", "话痨", "广播")),
    ("信息查询", ("天气", "新闻", "早报", "解析", "链接", "查分")),
    ("游戏", ("osu", "maimai", "谱面", "mcc")),
    ("娱乐", ("运势", "兽图", "兽设", "骰", "投票", "吃什么")),
    ("系统", ("运行状态", "版本哈希", "沙箱")),
    ("工具", ("加字", "反馈", "echo")),
)

_SLASH_CMD = re.compile(r"/([^\s，,。；;：:]+)")


@dataclass(frozen=True)
class HelpEntry:
    key: str
    name: str
    label: str
    description: str
    usage: str
    category: str
    commands: tuple[str, ...]


@dataclass
class HelpCategory:
    name: str
    labels: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.labels)


@dataclass
class HelpView:
    kind: str
    title: str = ""
    subtitle: str = ""
    footer: str = ""
    text: str = ""
    page: int = 1
    pages: int = 1
    categories: list[HelpCategory] = field(default_factory=list)
    plugins: list[HelpEntry] = field(default_factory=list)

    def plain_text(self) -> str:
        if self.kind == "hint":
            return self.text
        lines = [self.title, self.subtitle]
        for category in self.categories:
            lines.append(f"{category.name}（{category.count}）")
            lines.append("、".join(category.labels))
        for plugin in self.plugins:
            lines.append(f"{plugin.label}：{plugin.description}")
            if self.kind != "overview":
                lines.append(plugin.usage)
        if self.footer:
            lines.append(self.footer)
        return "\n".join(line for line in lines if line)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def extract_commands(usage: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _SLASH_CMD.finditer(usage or ""):
        token = match.group(1).strip("<>「」")
        if token and token not in found:
            found.append(token)
    return tuple(found)


def display_label(name: str, usage: str) -> str:
    cleaned = (name or "").strip()
    if _has_cjk(cleaned):
        return cleaned
    commands = extract_commands(usage)
    if commands:
        return commands[0]
    return cleaned or "未命名"


def resolve_category(meta: dict) -> str:
    explicit = str(meta.get("category") or "").strip()
    if explicit:
        return explicit
    name = str(meta.get("name") or "").strip()
    mapped = _NAME_CATEGORY.get(name.casefold()) or _NAME_CATEGORY.get(name)
    if mapped:
        return mapped
    blob = " ".join(
        str(meta.get(key) or "") for key in ("name", "description", "usage")
    ).casefold()
    for category, words in _KEYWORD_RULES:
        if any(word.casefold() in blob for word in words):
            return category
    return FALLBACK_CATEGORY


def build_entries(plugins: dict) -> list[HelpEntry]:
    entries: list[HelpEntry] = []
    for key, meta in (plugins or {}).items():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or key)
        description = str(meta.get("description") or "暂无描述")
        usage = str(meta.get("usage") or "暂无用法")
        entries.append(
            HelpEntry(
                key=str(key),
                name=name,
                label=display_label(name, usage),
                description=description,
                usage=usage,
                category=resolve_category(meta),
                commands=extract_commands(usage),
            )
        )
    entries.sort(key=lambda item: (category_rank(item.category), item.label, item.name))
    return entries


def category_rank(name: str) -> tuple[int, str]:
    try:
        return (CATEGORY_ORDER.index(name), name)
    except ValueError:
        return (len(CATEGORY_ORDER), name)


def group_categories(entries: Iterable[HelpEntry]) -> list[HelpCategory]:
    grouped: dict[str, HelpCategory] = {}
    for entry in entries:
        bucket = grouped.setdefault(entry.category, HelpCategory(entry.category))
        bucket.labels.append(entry.label)
    return sorted(grouped.values(), key=lambda item: category_rank(item.name))


def card_height(entry: HelpEntry) -> int:
    usage_lines = max(1, (entry.usage or "").count("\n") + 1)
    desc = entry.description or ""
    desc_lines = max(1, (len(desc) + 31) // 32)
    return _CARD_BASE_PX + desc_lines * _LINE_PX + usage_lines * _LINE_PX


def overview_height(categories: list[HelpCategory]) -> int:
    height = _PAGE_CHROME_PX
    for category in categories:
        names = "、".join(category.labels) or "暂无"
        lines = max(1, (len(names) + _NAME_CHARS_PER_LINE - 1) // _NAME_CHARS_PER_LINE)
        height += 32 + 36 + lines * _LINE_PX + 14
    return height


def paginate(entries: list[HelpEntry], budget: int = PAGE_BUDGET_PX) -> list[list[HelpEntry]]:
    pages: list[list[HelpEntry]] = []
    current: list[HelpEntry] = []
    used = _PAGE_CHROME_PX
    for entry in entries:
        height = card_height(entry)
        if current and used + height > budget:
            pages.append(current)
            current = [entry]
            used = _PAGE_CHROME_PX + height
        else:
            current.append(entry)
            used += height
    if current:
        pages.append(current)
    return pages or [[]]


def estimate_view_height(view: HelpView) -> int:
    if view.kind == "overview":
        return overview_height(view.categories)
    if view.kind in ("category", "plugin"):
        height = _PAGE_CHROME_PX
        for entry in view.plugins:
            height += card_height(entry)
        return height
    return 0


def _fold(text: str) -> str:
    return (text or "").strip().casefold()


def _example_category(categories: list[HelpCategory]) -> str:
    for preferred in ("娱乐", "工具", "信息查询"):
        if any(item.name == preferred for item in categories):
            return preferred
    return categories[0].name if categories else "娱乐"


def _example_plugin(entries: list[HelpEntry]) -> str:
    for entry in entries:
        if entry.label == "天气" or "天气" in entry.commands:
            return "天气"
    return entries[0].label if entries else "天气"


def _overview(entries: list[HelpEntry]) -> HelpView:
    categories = group_categories(entries)
    example_category = _example_category(categories)
    example_plugin = _example_plugin(entries)
    return HelpView(
        kind="overview",
        title="功能列表",
        subtitle=f"已加载 {len(entries)} 个功能",
        footer=f"看某一类：/help {example_category}\n看某一个：/help {example_plugin}",
        categories=categories,
        plugins=list(entries),
    )


def _category_view(entries: list[HelpEntry], category: str, page: int) -> HelpView:
    matched = [item for item in entries if item.category == category]
    pages = paginate(matched)
    if page < 1:
        return HelpView(kind="hint", text=f"页码从 1 开始。{category} 一共 {len(pages)} 页。")
    if page > len(pages):
        return HelpView(kind="hint", text=f"没有第 {page} 页。{category} 一共 {len(pages)} 页。")
    footer_bits = []
    if page > 1:
        previous = f"/help {category}" if page == 2 else f"/help {category} {page - 1}"
        footer_bits.append(f"上一页：{previous}")
    if page < len(pages):
        footer_bits.append(f"下一页：/help {category} {page + 1}")
    else:
        footer_bits.append("返回总览：/help")
    return HelpView(
        kind="category",
        title=category,
        subtitle=f"第 {page}/{len(pages)} 页",
        footer="\n".join(footer_bits),
        page=page,
        pages=len(pages),
        plugins=pages[page - 1],
    )


def _plugin_view(entry: HelpEntry) -> HelpView:
    return HelpView(
        kind="plugin",
        title=entry.label,
        subtitle=entry.category,
        footer=f"返回这一类：/help {entry.category}",
        plugins=[entry],
    )


def _hint(query: str, entries: list[HelpEntry]) -> HelpView:
    choices: list[str] = []
    seen = set()
    for entry in entries:
        for label in (entry.label, entry.name, entry.category, *entry.commands):
            cleaned = label.strip()
            folded = _fold(cleaned)
            if cleaned and folded not in seen:
                seen.add(folded)
                choices.append(cleaned)
    matches = get_close_matches(query.strip(), choices, n=3, cutoff=0.45)
    if matches:
        hints = "、".join(f"/help {item}" for item in matches)
        text = f"没有找到「{query}」。你是不是想看：{hints}"
    else:
        text = f"没有找到「{query}」。发送 /help 看分类。"
    return HelpView(kind="hint", text=text)


def _find_plugin(entries: list[HelpEntry], query: str) -> Optional[HelpEntry]:
    folded = _fold(query)
    for entry in entries:
        if folded in {_fold(entry.label), _fold(entry.name), _fold(entry.key)}:
            return entry
        if any(_fold(command) == folded for command in entry.commands):
            return entry
    return None


def resolve_help(entries: list[HelpEntry], args: Optional[list[str]] = None) -> HelpView:
    parts = [part.strip() for part in (args or []) if part and part.strip()]
    if not parts:
        return _overview(entries)

    page: Optional[int] = None
    if len(parts) >= 2 and parts[-1].isdigit():
        page = int(parts[-1])
        parts = parts[:-1]
    query = " ".join(parts).strip()
    if not query:
        return HelpView(kind="hint", text="页码从 1 开始。发送 /help 看分类。")

    categories = {item.category for item in entries}
    if query in categories:
        return _category_view(entries, query, 1 if page is None else page)

    if page is not None:
        return _hint(query, entries)

    plugin = _find_plugin(entries, query)
    if plugin is not None:
        return _plugin_view(plugin)
    return _hint(query, entries)


def template_data(view: HelpView) -> dict:
    return {
        "mode": view.kind,
        "title": view.title,
        "subtitle": view.subtitle,
        "footer": view.footer,
        "categories": [
            {"name": item.name, "count": item.count, "names": "、".join(item.labels)}
            for item in view.categories
        ],
        "plugins": [
            {
                "name": item.label,
                "description": item.description,
                "usage": item.usage,
                "category": item.category,
            }
            for item in view.plugins
        ],
    }
