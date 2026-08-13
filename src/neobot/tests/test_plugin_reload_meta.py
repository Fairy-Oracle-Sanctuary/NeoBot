from neobot.core.managers.command_manager import CommandManager

class TestPluginReloadMeta:
    def test_plugin_meta_persistence(self):
        """
        测试插件加载、卸载和重载过程中元信息的持久性
        """
        # 初始化 CommandManager
        command_manager = CommandManager(prefixes=("/",))
        
        # 模拟插件名称和元信息
        plugin_name = "plugins.test_plugin"
        plugin_meta = {
            "name": "测试插件",
            "description": "这是一个测试插件",
            "usage": "/test"
        }
        
        # 1. 模拟加载插件
        command_manager.plugins[plugin_name] = plugin_meta
        
        # 验证元信息已注册
        assert plugin_name in command_manager.plugins
        assert command_manager.plugins[plugin_name] == plugin_meta
        
        # 2. 模拟卸载插件
        command_manager.unload_plugin(plugin_name)
        
        # 验证元信息已移除
        assert plugin_name not in command_manager.plugins
        
        # 3. 模拟重载插件（重新注册元信息）
        # 在实际运行中，PluginManager 会在 reload 后重新赋值
        command_manager.plugins[plugin_name] = plugin_meta
        
        # 验证元信息已恢复
        assert plugin_name in command_manager.plugins
        assert command_manager.plugins[plugin_name] == plugin_meta
        
    def test_unload_plugin_exact_match(self):
        """
        测试 unload_plugin 是否只移除精确匹配的插件元信息
        """
        command_manager = CommandManager(prefixes=("/",))
        
        plugin1 = "plugins.test"
        plugin2 = "plugins.test_extra"
        
        command_manager.plugins[plugin1] = {"name": "Test 1"}
        command_manager.plugins[plugin2] = {"name": "Test 2"}
        
        # 卸载 plugin1
        command_manager.unload_plugin(plugin1)
        
        # 验证 plugin1 被移除，但 plugin2 仍然存在
        assert plugin1 not in command_manager.plugins
        assert plugin2 in command_manager.plugins
