"""日志保留天数：默认 7 天，只由配置决定，不再写死成 1 天。"""
from pathlib import Path

from neobot.core.utils.logger import DEFAULT_RETENTION_DAYS, resolve_retention_days


def test_retention_defaults_to_seven_days():
    assert DEFAULT_RETENTION_DAYS == 7
    assert resolve_retention_days(None) == 7
    assert resolve_retention_days("") == 7
    assert resolve_retention_days("nope") == 7
    assert resolve_retention_days(0) == 7
    assert resolve_retention_days(-3) == 7
    assert resolve_retention_days("14") == 14


def test_logger_does_not_pin_one_day():
    source = Path("src/neobot/core/utils/logger.py").read_text(encoding="utf-8")
    assert 'retention="1 day"' not in source
    assert "retention='1 day'" not in source
    assert source.count("logger.add(") == 2
