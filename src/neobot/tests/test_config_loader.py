import pytest
from neobot.core.config_loader import Config
from neobot.core.config_models import ConfigModel, NapCatWSModel, BotModel, RedisModel, DockerModel


class TestConfigLoader:
    def test_config_initialization(self, tmp_path):
        """测试配置加载器初始化。"""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[napcat_ws]
uri = "ws://localhost:3560"
token = "test_token"

[bot]
command = ["/"]
ignore_self_message = true
permission_denied_message = "权限不足，需要 {permission_name} 权限"

[redis]
host = "localhost"
port = 6379
db = 0
password = ""

[mysql]
host = "localhost"
port = 3306
user = "root"
password = ""
db = "neobot"

[docker]
base_url = "unix:///var/run/docker.sock"
sandbox_image = "python-sandbox:latest"
timeout = 10
concurrency_limit = 5
tls_verify = false

[image_manager]
image_height = 1920
image_width = 1080

[reverse_ws]
enabled = false
host = "0.0.0.0"
port = 3002
""", encoding='utf-8')
        config = Config(str(config_file))
        assert config.path == config_file
        assert isinstance(config._model, ConfigModel)

    def test_config_properties(self, tmp_path):
        """测试配置属性访问。"""
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[napcat_ws]
uri = "ws://localhost:3560"
token = "test_token"
reconnect_interval = 5

[bot]
command = ["/"]
ignore_self_message = true
permission_denied_message = "权限不足，需要 {permission_name} 权限"

[redis]
host = "localhost"
port = 6379
db = 0
password = ""

[mysql]
host = "localhost"
port = 3306
user = "root"
password = ""
db = "neobot"

[docker]
base_url = "unix:///var/run/docker.sock"
sandbox_image = "python-sandbox:latest"
timeout = 10
concurrency_limit = 5
tls_verify = false

[image_manager]
image_height = 1920
image_width = 1080

[reverse_ws]
enabled = false
host = "0.0.0.0"
port = 3002
""", encoding='utf-8')
        config = Config(str(config_file))
        assert isinstance(config.napcat_ws, NapCatWSModel)
        assert config.napcat_ws.uri == "ws://localhost:3560"
        assert config.napcat_ws.token == "test_token"
        assert config.napcat_ws.reconnect_interval == 5
        assert isinstance(config.bot, BotModel)
        assert config.bot.command == ["/"]
        assert config.bot.ignore_self_message is True
        assert config.bot.permission_denied_message == "权限不足，需要 {permission_name} 权限"
        assert isinstance(config.redis, RedisModel)
        assert config.redis.host == "localhost"
        assert config.redis.port == 6379
        assert config.redis.db == 0
        assert config.redis.password == ""
        assert isinstance(config.docker, DockerModel)
        assert config.docker.base_url == "unix:///var/run/docker.sock"
        assert config.docker.sandbox_image == "python-sandbox:latest"
        assert config.docker.timeout == 10
        assert config.docker.concurrency_limit == 5
        assert config.docker.tls_verify is False

    def test_config_file_not_found(self, tmp_path):
        """测试配置文件不存在时的错误处理。"""
        config_file = tmp_path / "non_existent_config.toml"
        # 当前实现会尝试从示例配置文件生成新配置
        # 如果示例配置存在，会自动创建配置文件
        config = Config(str(config_file))
        assert config.path == config_file
        assert config_file.exists()  # 配置文件已被创建

    def test_config_invalid_format(self, tmp_path):
        """测试配置文件格式错误时的错误处理。"""
        config_file = tmp_path / "invalid_config.toml"
        config_file.write_text("invalid toml format", encoding='utf-8')
        with pytest.raises(Exception):
            Config(str(config_file))

    def test_config_validation_error(self, tmp_path):
        """测试配置验证失败时的错误处理。"""
        config_file = tmp_path / "invalid_config.toml"
        config_file.write_text("""
[napcat_ws]
uri = "ws://localhost:3560"

[bot]
command = ["/"]
ignore_self_message = true
permission_denied_message = "权限不足，需要 {permission_name} 权限"

[redis]
host = "localhost"
port = 6379
db = 0
password = ""

[docker]
base_url = "unix:///var/run/docker.sock"
sandbox_image = "python-sandbox:latest"
timeout = 10
concurrency_limit = 5
tls_verify = false
""", encoding='utf-8')
        with pytest.raises(Exception):
            Config(str(config_file))