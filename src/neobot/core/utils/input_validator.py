"""
输入验证工具

提供通用的输入验证功能，防止 SQL 注入、XSS 攻击等安全问题。
"""
import re
import html
import ipaddress
from typing import Optional, List, Dict
from urllib.parse import urlparse

from .logger import ModuleLogger


class InputValidator:
    """
    输入验证器类
    """
    
    def __init__(self):
        self.logger = ModuleLogger("InputValidator")
        
        # SQL 注入检测模式（预编译正则表达式）
        # 注意：仅匹配真正具备注入语义的结构，避免对包含 and/or/from 等普通英文单词的
        # 正常输入产生误报。如需更严格校验，应在 SQL 拼接处使用参数化查询。
        self.sql_injection_patterns = [
            # 经典注入结构：' or '1'='1  /  ") or ("1"="1
            re.compile(r"(?i)(['\"]\s*(or|and)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+)"),
            # UNION 注入：union select
            re.compile(r"(?i)\bunion\b\s+\bselect\b"),
            # 裸 SELECT 读取语句（默认视为危险；allow_safe_keywords=True 时放行）
            re.compile(r"(?i)\bselect\b.*\bfrom\b"),
            # 裸 DDL/DML 关键字（DROP/DELETE 等，默认视为危险）
            re.compile(r"(?i)\b(drop|truncate|delete|alter|insert|update|create|exec|execute)\s"),
            # 注释符序列
            re.compile(r"(--\s|/\*|\*/|;--|#--)"),
            # 危险的堆叠查询分隔符（仅在 SQL 上下文中才应触发）
            re.compile(r";\s*(drop|delete|truncate|alter|create|insert|update)\s", re.IGNORECASE),
            # 危险存储过程
            re.compile(r"(?i)\b(xp_cmdshell|sp_executesql|sp_oacreate)\b"),
            # 十六进制字面量拼接（常用于绕过 WAF）
            re.compile(r"(?i)0x[0-9a-f]{8,}"),
            # 信息收集类：load_file / outfile / benchmark 等
            re.compile(r"(?i)\b(load_file|into\s+outfile|benchmark\s*\(|sleep\s*\(\s*\d+\s*\)|pg_sleep\s*\()"),
        ]
        
        # XSS 攻击检测模式（预编译正则表达式）
        self.xss_patterns = [
            re.compile(r"(<script[^>]*>.*?</script>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<iframe[^>]*>.*?</iframe>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<object[^>]*>.*?</object>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<embed[^>]*>.*?</embed>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<applet[^>]*>.*?</applet>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<meta[^>]*>.*?</meta>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<link[^>]*>.*?</link>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<style[^>]*>.*?</style>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<base[^>]*>.*?</base>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<form[^>]*>.*?</form>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<input[^>]*>.*?</input>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<button[^>]*>.*?</button>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<select[^>]*>.*?</select>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<textarea[^>]*>.*?</textarea>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<img[^>]*>.*?</img>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<svg[^>]*>.*?</svg>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(<math[^>]*>.*?</math>)", re.IGNORECASE | re.DOTALL),
            re.compile(r"(javascript:|data:|vbscript:|about:|file:|ftp:|mailto:|telnet:)", re.IGNORECASE),
            re.compile(r"(on\w+\s*=)", re.IGNORECASE),
            re.compile(r"(expression\s*\()", re.IGNORECASE),
            re.compile(r"(url\s*\()", re.IGNORECASE),
        ]
        
        # 路径遍历检测模式（预编译正则表达式）
        self.path_traversal_patterns = [
            re.compile(r"(\.\./|\.\.\\)", re.IGNORECASE),
            re.compile(r"(/etc/passwd|/etc/shadow|/etc/hosts)", re.IGNORECASE),
            re.compile(r"(C:\\Windows\\System32|C:\\Windows\\SysWOW64)", re.IGNORECASE),
            re.compile(r"(/bin/sh|/bin/bash|/usr/bin/python)", re.IGNORECASE),
            re.compile(r"(\.\.%2f|\.\.%5c)", re.IGNORECASE),
        ]
        
        # 命令注入检测模式（预编译正则表达式）
        self.command_injection_patterns = [
            re.compile(r"(;|\||&|\$\(|\`|\n|\r)"),
            re.compile(r"(rm\s+-rf|del\s+/f|format\s+)", re.IGNORECASE),
            re.compile(r"(shutdown|reboot|halt|poweroff)", re.IGNORECASE),
            re.compile(r"(wget|curl|ftp|scp|ssh)\s+", re.IGNORECASE),
            re.compile(r"(nc|netcat|telnet|nmap)\s+", re.IGNORECASE),
        ]
        
        # 预编译常用正则表达式
        self.email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        self.phone_pattern = re.compile(r'^1[3-9]\d{9}$')
        self.nine_digit_pattern = re.compile(r'^\d{9}$')  # 用于城市代码验证
    
    def validate_sql_input(self, input_str: str, allow_safe_keywords: bool = False) -> bool:
        """
        验证 SQL 输入是否安全
        
        Args:
            input_str: 输入字符串
            allow_safe_keywords: 是否允许安全的 SQL 关键字
            
        Returns:
            bool: 是否安全
        """
        if not input_str:
            return True
            
        input_lower = input_str.lower()
        
        if allow_safe_keywords:
            # 只检查危险操作
            dangerous_operations = ['drop', 'delete', 'truncate', 'alter', 'create table', 'exec', 'execute']
            for op in dangerous_operations:
                if op in input_lower:
                    self.logger.warning(f"检测到危险 SQL 操作: {op}")
                    return False
        else:
            # 检查所有 SQL 注入模式（使用预编译的正则表达式）
            for pattern in self.sql_injection_patterns:
                if pattern.search(input_lower):
                    self.logger.warning(f"检测到可能的 SQL 注入: {input_str}")
                    return False
        
        return True
    
    def validate_xss_input(self, input_str: str) -> bool:
        """
        验证 XSS 输入是否安全
        
        Args:
            input_str: 输入字符串
            
        Returns:
            bool: 是否安全
        """
        if not input_str:
            return True
            
        # 检查 XSS 攻击模式（使用预编译的正则表达式）
        for pattern in self.xss_patterns:
            if pattern.search(input_str):
                self.logger.warning(f"检测到可能的 XSS 攻击: {input_str}")
                return False
        
        return True
    
    def validate_path_input(self, input_str: str) -> bool:
        """
        验证路径输入是否安全
        
        Args:
            input_str: 输入字符串
            
        Returns:
            bool: 是否安全
        """
        if not input_str:
            return True
            
        # 检查路径遍历攻击（使用预编译的正则表达式）
        for pattern in self.path_traversal_patterns:
            if pattern.search(input_str):
                self.logger.warning(f"检测到可能的路径遍历攻击: {input_str}")
                return False
        
        return True
    
    def validate_command_input(self, input_str: str) -> bool:
        """
        验证命令输入是否安全
        
        Args:
            input_str: 输入字符串
            
        Returns:
            bool: 是否安全
        """
        if not input_str:
            return True
            
        # 检查命令注入攻击（使用预编译的正则表达式）
        for pattern in self.command_injection_patterns:
            if pattern.search(input_str):
                self.logger.warning(f"检测到可能的命令注入攻击: {input_str}")
                return False
        
        return True
    
    def validate_url(self, url: str, allowed_schemes: List[str] = None) -> bool:
        """
        验证 URL 是否安全
        
        Args:
            url: URL 字符串
            allowed_schemes: 允许的协议列表
            
        Returns:
            bool: 是否安全
        """
        if not url:
            return False
            
        if allowed_schemes is None:
            allowed_schemes = ['http', 'https', 'ftp', 'file']
        
        try:
            parsed = urlparse(url)
            
            # 检查协议
            if parsed.scheme not in allowed_schemes:
                self.logger.warning(f"不允许的协议: {parsed.scheme}")
                return False
            
            # 检查主机名
            if not parsed.hostname:
                self.logger.warning("URL 缺少主机名")
                return False
            
            # 检查路径安全性
            if not self.validate_path_input(parsed.path):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"URL 解析失败: {e}")
            return False

    def _is_private_or_loopback_host(self, hostname: str) -> bool:
        """
        判断主机名是否指向内网 / 回环 / 链路本地地址，用于 SSRF 防护。
        仅拦截字面量 IP 与保留主机名（localhost），域名无法在此解析判定。
        """
        host = (hostname or "").strip().lower().rstrip(".")
        if not host:
            return True
        # 保留主机名
        if host in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
            return True
        # 尝试按 IP 字面量解析
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return False
        return (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified)

    def validate_http_url(self, url: str, allow_private: bool = False) -> bool:
        """
        验证 URL 是否可安全发起 HTTP 请求（SSRF 防护）。

        仅允许 http/https 协议，且默认拒绝指向内网 / 回环 / 链路本地的地址
        （127.x、10.x、172.16-31.x、192.168.x、169.254.x、::1、fe80:: 等）。

        Args:
            url: 目标 URL
            allow_private: 是否允许内网地址（默认 False）

        Returns:
            bool: 是否安全
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
        except Exception as e:
            self.logger.error(f"URL 解析失败: {e}")
            return False
        if parsed.scheme not in ("http", "https"):
            self.logger.warning(f"SSRF 防护: 不允许的协议 {parsed.scheme!r}: {url[:200]}")
            return False
        if not parsed.hostname:
            self.logger.warning("SSRF 防护: URL 缺少主机名")
            return False
        if not allow_private and self._is_private_or_loopback_host(parsed.hostname):
            self.logger.warning(f"SSRF 防护: 拒绝内网/回环地址 {parsed.hostname!r}: {url[:200]}")
            return False
        return True
    
    def validate_email(self, email: str) -> bool:
        """
        验证邮箱地址格式
        
        Args:
            email: 邮箱地址
            
        Returns:
            bool: 是否有效
        """
        if not email:
            return False
            
        return bool(self.email_pattern.match(email))
    
    def validate_phone(self, phone: str) -> bool:
        """
        验证手机号码格式
        
        Args:
            phone: 手机号码
            
        Returns:
            bool: 是否有效
        """
        if not phone:
            return False
            
        return bool(self.phone_pattern.match(phone))
    
    def validate_integer(self, value: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> bool:
        """
        验证整数格式和范围
        
        Args:
            value: 整数字符串
            min_value: 最小值
            max_value: 最大值
            
        Returns:
            bool: 是否有效
        """
        if not value:
            return False
            
        try:
            int_value = int(value)
            
            if min_value is not None and int_value < min_value:
                return False
                
            if max_value is not None and int_value > max_value:
                return False
                
            return True
            
        except ValueError:
            return False
    
    def validate_float(self, value: str, min_value: Optional[float] = None, max_value: Optional[float] = None) -> bool:
        """
        验证浮点数格式和范围
        
        Args:
            value: 浮点数字符串
            min_value: 最小值
            max_value: 最大值
            
        Returns:
            bool: 是否有效
        """
        if not value:
            return False
            
        try:
            float_value = float(value)
            
            if min_value is not None and float_value < min_value:
                return False
                
            if max_value is not None and float_value > max_value:
                return False
                
            return True
            
        except ValueError:
            return False
    
    def sanitize_html(self, html_str: str) -> str:
        """
        清理 HTML 字符串，防止 XSS 攻击
        
        Args:
            html_str: HTML 字符串
            
        Returns:
            str: 清理后的字符串
        """
        if not html_str:
            return ""
            
        # 转义 HTML 特殊字符
        sanitized = html.escape(html_str)
        
        # 将 onXXX= 属性替换为 data-XXX=（移除 on 前缀）
        sanitized = re.sub(r'on(\w+)(\s*=)', r'data-\1\2', sanitized, flags=re.IGNORECASE)
        # 将 javascript: 协议替换为 data:
        sanitized = re.sub(r'javascript:', 'data:', sanitized, flags=re.IGNORECASE)
        # 将 vbscript: 协议替换为 data:
        sanitized = re.sub(r'vbscript:', 'data:', sanitized, flags=re.IGNORECASE)
        
        return sanitized
    
    def sanitize_sql(self, sql_str: str) -> str:
        """
        清理 SQL 字符串，防止 SQL 注入
        
        Args:
            sql_str: SQL 字符串
            
        Returns:
            str: 清理后的字符串
        """
        if not sql_str:
            return ""
            
        # 移除注释
        sanitized = re.sub(r'--.*$', '', sql_str, flags=re.MULTILINE)
        sanitized = re.sub(r'/\*.*?\*/', '', sanitized, flags=re.DOTALL)
        
        # 移除分号（在参数化查询中不需要）
        sanitized = sanitized.replace(';', '')
        
        return sanitized
    
    def validate_all(self, input_str: str, validation_types: List[str] = None) -> Dict[str, bool]:
        """
        执行所有验证
        
        Args:
            input_str: 输入字符串
            validation_types: 验证类型列表
            
        Returns:
            Dict[str, bool]: 验证结果字典
        """
        if validation_types is None:
            validation_types = ['sql', 'xss', 'path', 'command']
        
        results = {}
        
        for vtype in validation_types:
            if vtype == 'sql':
                results['sql'] = self.validate_sql_input(input_str)
            elif vtype == 'xss':
                results['xss'] = self.validate_xss_input(input_str)
            elif vtype == 'path':
                results['path'] = self.validate_path_input(input_str)
            elif vtype == 'command':
                results['command'] = self.validate_command_input(input_str)
            elif vtype == 'url':
                results['url'] = self.validate_url(input_str)
            elif vtype == 'email':
                results['email'] = self.validate_email(input_str)
            elif vtype == 'phone':
                results['phone'] = self.validate_phone(input_str)
        
        return results


# 全局输入验证器实例
input_validator = InputValidator()