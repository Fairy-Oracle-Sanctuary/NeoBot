"""
环境变量加载器测试
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from neobot.core.utils.env_loader import EnvLoader


class TestEnvLoader:
    """环境变量加载器测试类"""

    def test_init_with_default_env_file(self):
        """测试使用默认 .env 文件初始化"""
        loader = EnvLoader()
        assert loader.env_file == Path(".env")
        assert not loader._loaded

    def test_init_with_custom_env_file(self):
        """测试使用自定义 .env 文件初始化"""
        loader = EnvLoader("custom.env")
        assert loader.env_file == Path("custom.env")

    def test_load_env_file_exists(self):
        """测试加载存在的 .env 文件"""
        # 创建临时 .env 文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_KEY=test_value\nANOTHER_KEY=another_value")
            env_file = f.name
        
        try:
            loader = EnvLoader(env_file)
            loader.load()
            
            assert loader._loaded
            assert loader.get("TEST_KEY") == "test_value"
            assert loader.get("ANOTHER_KEY") == "another_value"
        finally:
            os.unlink(env_file)

    def test_load_env_file_not_exists(self):
        """测试加载不存在的 .env 文件"""
        loader = EnvLoader("non_existent.env")
        loader.load()
        
        # 应该仍然加载成功，只是没有文件
        assert loader._loaded

    def test_get_existing_key(self):
        """测试获取存在的环境变量"""
        with patch.dict(os.environ, {"EXISTING_KEY": "existing_value"}):
            loader = EnvLoader()
            loader.load()
            
            value = loader.get("EXISTING_KEY")
            assert value == "existing_value"

    def test_get_non_existing_key_with_default(self):
        """测试获取不存在的环境变量（带默认值）"""
        loader = EnvLoader()
        loader.load()
        
        value = loader.get("NON_EXISTING_KEY", "default_value")
        assert value == "default_value"

    def test_get_non_existing_key_without_default(self):
        """测试获取不存在的环境变量（不带默认值）"""
        loader = EnvLoader()
        loader.load()
        
        value = loader.get("NON_EXISTING_KEY")
        assert value is None

    def test_get_int_existing_key(self):
        """测试获取整数类型的环境变量"""
        with patch.dict(os.environ, {"INT_KEY": "123"}):
            loader = EnvLoader()
            loader.load()
            
            value = loader.get_int("INT_KEY")
            assert value == 123

    def test_get_int_non_existing_key_with_default(self):
        """测试获取不存在的整数环境变量（带默认值）"""
        loader = EnvLoader()
        loader.load()
        
        value = loader.get_int("NON_EXISTING_INT", 456)
        assert value == 456

    def test_get_int_invalid_value(self):
        """测试获取无效的整数环境变量"""
        with patch.dict(os.environ, {"INVALID_INT": "not_a_number"}):
            loader = EnvLoader()
            loader.load()
            
            value = loader.get_int("INVALID_INT", 789)
            assert value == 789

    def test_get_bool_true_values(self):
        """测试获取布尔类型的环境变量（真值）"""
        true_values = ["true", "True", "TRUE", "yes", "Yes", "YES", "1", "on", "On", "ON"]
        
        for i, value in enumerate(true_values):
            with patch.dict(os.environ, {f"BOOL_KEY_{i}": value}):
                loader = EnvLoader()
                loader.load()
                
                bool_value = loader.get_bool(f"BOOL_KEY_{i}")
                assert bool_value is True

    def test_get_bool_false_values(self):
        """测试获取布尔类型的环境变量（假值）"""
        false_values = ["false", "False", "FALSE", "no", "No", "NO", "0", "off", "Off", "OFF"]
        
        for i, value in enumerate(false_values):
            with patch.dict(os.environ, {f"BOOL_KEY_{i}": value}):
                loader = EnvLoader()
                loader.load()
                
                bool_value = loader.get_bool(f"BOOL_KEY_{i}")
                assert bool_value is False

    def test_get_bool_invalid_value(self):
        """测试获取无效的布尔环境变量"""
        with patch.dict(os.environ, {"INVALID_BOOL": "maybe"}):
            loader = EnvLoader()
            loader.load()
            
            value = loader.get_bool("INVALID_BOOL", False)
            assert value is False

    def test_mask_sensitive_value_short(self):
        """测试掩码短敏感值"""
        loader = EnvLoader()
        
        # 长度小于等于4的值
        assert loader.mask_sensitive_value("") == ""
        assert loader.mask_sensitive_value("a") == "***"
        assert loader.mask_sensitive_value("ab") == "***"
        assert loader.mask_sensitive_value("abc") == "***"
        assert loader.mask_sensitive_value("abcd") == "***"

    def test_mask_sensitive_value_long(self):
        """测试掩码长敏感值"""
        loader = EnvLoader()
        
        # 长度大于4的值
        assert loader.mask_sensitive_value("password123") == "pa***23"
        assert loader.mask_sensitive_value("secret_key_abc") == "se***bc"
        assert loader.mask_sensitive_value("token_xyz_123") == "to***23"

    def test_get_masked_sensitive_key(self):
        """测试获取掩码的敏感键值"""
        sensitive_keys = [
            "MYSQL_PASSWORD",
            "REDIS_PASSWORD", 
            "DISCORD_TOKEN",
            "BILIBILI_SESSDATA",
            "SECRET_KEY",
            "API_TOKEN",
        ]
        
        for key in sensitive_keys:
            with patch.dict(os.environ, {key: "very_secret_value_123"}):
                loader = EnvLoader()
                loader.load()
                
                masked = loader.get_masked(key)
                assert masked == "ve***23"  # 前2个字符 + *** + 后2个字符

    def test_get_masked_non_sensitive_key(self):
        """测试获取非敏感键值（不掩码）"""
        non_sensitive_keys = [
            "MYSQL_HOST",
            "REDIS_HOST",
            "LOG_LEVEL",
            "APP_NAME",
        ]
        
        for key in non_sensitive_keys:
            with patch.dict(os.environ, {key: "normal_value"}):
                loader = EnvLoader()
                loader.load()
                
                value = loader.get_masked(key)
                assert value == "normal_value"

    def test_get_masked_non_existing_key(self):
        """测试获取不存在的键的掩码值"""
        loader = EnvLoader()
        loader.load()
        
        value = loader.get_masked("NON_EXISTING_KEY")
        assert value == "<未设置>"

    def test_validate_required_keys_all_present(self):
        """测试验证必需的键（全部存在）"""
        required_keys = ["KEY1", "KEY2", "KEY3"]
        
        with patch.dict(os.environ, {"KEY1": "value1", "KEY2": "value2", "KEY3": "value3"}):
            loader = EnvLoader()
            loader.load()
            
            # 应该不抛出异常
            loader.validate_required_keys(required_keys)

    def test_validate_required_keys_missing(self):
        """测试验证必需的键（有缺失）"""
        required_keys = ["KEY1", "KEY2", "MISSING_KEY"]
        
        with patch.dict(os.environ, {"KEY1": "value1", "KEY2": "value2"}):
            loader = EnvLoader()
            loader.load()
            
            # 应该抛出 ValueError
            with pytest.raises(ValueError) as exc_info:
                loader.validate_required_keys(required_keys)
            
            assert "MISSING_KEY" in str(exc_info.value)

    def test_global_env_loader_instance(self):
        """测试全局环境变量加载器实例"""
        from neobot.core.utils.env_loader import env_loader
        
        assert isinstance(env_loader, EnvLoader)
        assert env_loader.env_file == Path(".env")

    @pytest.mark.asyncio
    async def test_async_compatibility(self):
        """测试异步兼容性"""
        # 确保在异步环境中也能正常工作
        loader = EnvLoader()
        loader.load()
        
        # 模拟异步环境中的使用，确保 TEST_KEY 不在环境中
        if "TEST_KEY" in os.environ:
            del os.environ["TEST_KEY"]
        
        value = loader.get("TEST_KEY", "default")
        assert value == "default"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])