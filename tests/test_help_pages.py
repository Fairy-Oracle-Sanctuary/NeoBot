""" /help 分成总览、分类页和单插件页，分类页超高就分页。"""
from neobot.core.help_pages import (
    PAGE_BUDGET_PX,
    FALLBACK_CATEGORY,
    build_entries,
    estimate_view_height,
    resolve_help,
)
from neobot.plugin_api.manifest import define_plugin


def _meta(name, description, usage, category=""):
    return {
        "name": name,
        "description": description,
        "usage": usage,
        "category": category,
    }


def _catalog():
    plugins = {
        "weather": _meta("weather", "查询天气信息", "/天气 南京\n/天气 北京"),
        "daily": _meta("daily", "每天的一点小事：运势和今天吃什么", "/今日运势\n/今天吃什么"),
        "dice": _meta("dice", "掷骰和简易 COC 检定", "/骰\n/coc"),
        "reminder": _meta("reminder", "到点在群里提醒你", "/提醒 30分钟 喝水"),
        "mystery": _meta("zzz_plugin", "没有标明分类的小功能", "/zzz"),
        "tagged": _meta("custom_tool", "自己标明了分类", "/自定义", category="工具"),
    }
    return build_entries(plugins)


def test_unlabelled_plugin_uses_fallback_and_explicit_category_wins():
    entries = _catalog()
    by_name = {item.name: item for item in entries}
    assert by_name["zzz_plugin"].category == FALLBACK_CATEGORY
    assert by_name["custom_tool"].category == "工具"
    assert by_name["weather"].category == "信息查询"
    assert by_name["weather"].label == "天气"
    stored = define_plugin(name="demo_plugin", category="娱乐").to_dict()
    assert stored["category"] == "娱乐"


def test_overview_lists_names_without_usages_and_stays_short():
    entries = _catalog()
    # 再塞一批插件，确认总览仍然是一屏能看完的高度。
    extra = {}
    buckets = ("工具", "娱乐", "群管理", "信息查询", "游戏", "系统")
    for index in range(36):
        extra[f"p{index}"] = _meta(
            f"fun_{index}",
            "小功能",
            f"/玩{index}",
            category=buckets[index % len(buckets)],
        )
    base = {
        item.name: _meta(item.name, item.description, item.usage, item.category)
        for item in entries
    }
    entries = build_entries({**base, **extra})
    view = resolve_help(entries, [])
    assert view.kind == "overview"
    assert view.footer.count("/help") >= 2
    assert "娱乐" in view.footer or "/help" in view.footer
    joined = " ".join("、".join(item.labels) for item in view.categories)
    assert "天气" in joined
    assert "/天气 南京" not in joined
    assert estimate_view_height(view) < PAGE_BUDGET_PX


def test_category_page_paginates_and_names_the_page():
    plugins = {}
    for index in range(12):
        usage = "\n".join(f"/玩{index} 第{line}行" for line in range(6))
        plugins[f"fun{index}"] = _meta("dice", f"第 {index} 个小游戏", usage, category="娱乐")
        plugins[f"fun{index}"]["name"] = f"game_{index}"
    entries = build_entries(plugins)
    first = resolve_help(entries, ["娱乐"])
    assert first.kind == "category"
    assert first.pages >= 2
    assert first.subtitle == f"第 1/{first.pages} 页"
    assert "/help 娱乐 2" in first.footer
    assert estimate_view_height(first) <= PAGE_BUDGET_PX
    second = resolve_help(entries, ["娱乐", "2"])
    assert second.kind == "category"
    assert second.page == 2
    assert second.subtitle == f"第 2/{second.pages} 页"
    assert second.plugins
    assert {item.name for item in first.plugins}.isdisjoint({item.name for item in second.plugins})
    missing = resolve_help(entries, ["娱乐", "9"])
    assert missing.kind == "hint"
    assert "没有第 9 页" in missing.text


def test_single_plugin_and_unknown_hint():
    entries = _catalog()
    plugin = resolve_help(entries, ["天气"])
    assert plugin.kind == "plugin"
    assert plugin.plugins[0].label == "天气"
    assert "/天气" in plugin.plugins[0].usage
    by_id = resolve_help(entries, ["weather"])
    assert by_id.kind == "plugin"
    hint = resolve_help(entries, ["天汽"])
    assert hint.kind == "hint"
    assert "/help 天气" in hint.text
    empty = resolve_help(entries, ["完全不存在的东西xyz"])
    assert empty.kind == "hint"
    assert "/help" in empty.text
