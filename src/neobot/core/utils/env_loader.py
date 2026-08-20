"""
环境变量加载器

负责从环境变量加载敏感配置，支持 .env 文件和环境变量。
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from .logger import ModuleLogger


class EnvLoader:
    """
    环境变量加载器类
    """
    
    def __init__(self, env_file: str = ".env"):
        """
        初始化环境变量加载器
        
        Args:
            env_file: .env 文件路径
        """
        self.env_file = Path(env_file)
        self.logger = ModuleLogger("EnvLoader")
        self._loaded = False
        
    def load(self) -> bool:
        """
        加载环境变量
        
        Returns:
            bool: 是否成功加载
        """
        if self._loaded:
            return True
            
        try:
            # 尝试从 .env 文件加载
            if self.env_file.exists():
                load_dotenv(self.env_file)
                self.logger.info(f"已从 {self.env_file} 加载环境变量")
            else:
                self.logger.warning(f".env 文件不存在: {self.env_file}")
                
            self._loaded = True
            return True
            
        except Exception as e:
            self.logger.error(f"加载环境变量失败: {e}")
            return False
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        获取环境变量值
        
        Args:
            key: 环境变量键名
            default: 默认值
            
        Returns:
            环境变量值，如果不存在则返回默认值
        """
        if not self._loaded:
            self.load()
            
        return os.getenv(key, default)
    
    def get_int(self, key: str, default: int = 0) -> int:
        """
        获取整数类型的环境变量值
        
        Args:
            key: 环境变量键名
            default: 默认值
            
        Returns:
            整数类型的环境变量值
        """
        value = self.get(key)
        if value is None:
            return default
            
        try:
            return int(value)
        except (ValueError, TypeError):
            self.logger.warning(f"环境变量 {key} 的值 '{value}' 不是有效的整数，使用默认值 {default}")
            return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        获取布尔类型的环境变量值
        
        Args:
            key: 环境变量键名
            default: 默认值
            
        Returns:
            布尔类型的环境变量值
        """
        value = self.get(key)
        if value is None:
            return default
            
        value_lower = value.lower()
        if value_lower in ('true', 'yes', '1', 'on'):
            return True
        elif value_lower in ('false', 'no', '0', 'off'):
            return False
        else:
            self.logger.warning(f"环境变量 {key} 的值 '{value}' 不是有效的布尔值，使用默认值 {default}")
            return default
    
    def get_list(self, key: str, default: Optional[list] = None, separator: str = ',') -> list:
        """
        获取列表类型的环境变量值
        
        Args:
            key: 环境变量键名
            default: 默认值
            separator: 分隔符
            
        Returns:
            列表类型的环境变量值
        """
        value = self.get(key)
        if value is None:
            return default or []
            
        return [item.strip() for item in value.split(separator) if item.strip()]
    
    def validate_required(self, keys: list[str]) -> bool:
        """
        验证必需的环境变量是否存在
        
        Args:
            keys: 必需的环境变量键名列表
            
        Returns:
            bool: 所有必需的环境变量是否存在
        """
        missing_keys = []
        
        for key in keys:
            if self.get(key) is None:
                missing_keys.append(key)
        
        if missing_keys:
            self.logger.error(f"缺少必需的环境变量: {', '.join(missing_keys)}")
            return False
            
        return True
    
    def mask_sensitive_value(self, value: str) -> str:
        """
        隐藏敏感值（用于日志输出）
        
        Args:
            value: 原始值
            
        Returns:
            隐藏后的值
        """
        if not value:
            return ""
            
        if len(value) <= 4:
            return "***"
        else:
            return value[:2] + "***" + value[-2:]
    
    def get_safe_log_value(self, key: str) -> str:
        """
        获取安全的日志值（隐藏敏感信息）
        
        Args:
            key: 环境变量键名
            
        Returns:
            安全的日志值
        """
        value = self.get(key)
        if value is None:
            return "<未设置>"
            
        # 敏感键名列表
        sensitive_keys = [
            'password', 'token', 'secret', 'key', 'credential',
            'sessdata', 'bili_jct', 'buvid3', 'dedeuserid'
        ]
        
        for sensitive in sensitive_keys:
            if sensitive in key.lower():
                return self.mask_sensitive_value(value)
                
        return value
    
    def get_masked(self, key: str) -> str:
        """
        获取隐藏敏感信息的值（别名方法）
        
        Args:
            key: 环境变量键名
            
        Returns:
            隐藏敏感信息后的值
        """
        return self.get_safe_log_value(key)
    
    def validate_required_keys(self, keys: list[str]) -> bool:
        """
        验证必需的环境变量是否存在（别名方法）
        
        Args:
            keys: 必需的环境变量键名列表
            
        Returns:
            bool: 所有必需的环境变量是否存在
            
        Raises:
            ValueError: 如果有缺失的必需键
        """
        if not self.validate_required(keys):
            missing_keys = [key for key in keys if self.get(key) is None]
            raise ValueError(f"缺少必需的环境变量: {', '.join(missing_keys)}")
        return True


# 全局环境变量加载器实例
env_loader = EnvLoader()