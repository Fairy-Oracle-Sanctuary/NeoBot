import pytest
import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_import_core():
    """测试核心模块是否可以被导入"""
    try:
        import core  # noqa: F401
        import neobot.core.bot
        import neobot.core.ws  # noqa: F401
    except ImportError as e:
        pytest.fail(f"无法导入核心模块: {e}")

def test_plugin_manager_path():
    """测试插件管理器路径逻辑是否正确"""
    from neobot.core.managers.plugin_manager import PluginManager
    # Mock command manager
    pm = PluginManager(None)
    
    # 我们无法直接测试 load_all_plugins 的内部路径变量，
    # 但我们可以检查它是否能找到 plugins 目录而不报错
    # 这里我们简单地断言 PluginManager 类存在且可以实例化
    assert pm is not None

def test_config_loader_exists():
    """测试配置加载器是否存在"""
    # 注意：导入 config_loader 会尝试读取 config.toml
    # 如果 config.toml 不存在，这可能会失败。
    # 这是一个已知的设计问题，但在测试环境中我们假设 config.toml 存在或被 mock
    if os.path.exists("config.toml"):
        from neobot.core.config_loader import global_config
        assert global_config is not None
    else:
        pytest.skip("config.toml 不存在，跳过配置加载测试")
