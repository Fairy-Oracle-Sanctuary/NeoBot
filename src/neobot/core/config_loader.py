"""
配置加载模块

负责读取和解析 config.toml 配置文件，提供全局配置对象。
支持从环境变量覆盖敏感配置。
"""
from pathlib import Path

import tomllib
from pydantic import ValidationError
from .config_models import ConfigModel, NapCatWSModel, BotModel, RedisModel, DockerModel, ImageManagerModel, MySQLModel, ReverseWSModel, ThreadingModel, BilibiliModel, DouyinModel, JinmanModel, EhentaiModel, DivingFishModel, LocalFileServerModel, DiscordModel, CrossPlatformModel, LoggingModel, McCAdapterModel
from .utils.logger import ModuleLogger
from .utils.exceptions import ConfigError, ConfigNotFoundError, ConfigValidationError
from .utils.env_loader import env_loader


class Config:
    """
    配置加载类，负责读取和解析 config.toml 文件
    支持从环境变量覆盖敏感配置
    """

    def __init__(self, file_path: str = "config.toml"):
        """
        初始化配置加载器

        :param file_path: 配置文件路径，默认为 "config.toml"
        """
        self.path = Path(file_path)
        self._model: ConfigModel
        # 创建模块专用日志记录器
        self.logger = ModuleLogger("ConfigLoader")
        # 加载环境变量
        env_loader.load()
        self.load()

    def load(self):
        """
        加载并验证配置文件

        :raises ConfigNotFoundError: 如果配置文件不存在
        :raises ConfigValidationError: 如果配置格式不正确
        :raises ConfigError: 如果加载配置时发生其他错误
        """
        # 检查配置文件权限
        self._check_file_permissions()
        
        if not self.path.exists():
            self.logger.warning(f"配置文件 {self.path} 未找到，正在生成示例配置...")
            self._generate_example_config()
            self.logger.success(f"示例配置已生成: {self.path}")
            self.logger.info("请编辑配置文件后重新启动程序")

        try:
            self.logger.info(f"正在从 {self.path} 加载配置...")
            with open(self.path, "rb") as f:
                raw_config = tomllib.load(f)
            
            # 从环境变量覆盖敏感配置
            raw_config = self._override_with_env_vars(raw_config)
            
            self._model = ConfigModel(**raw_config)
            self.logger.success("配置加载并验证成功！")

        except ValidationError as e:
            error_details = []
            for error in e.errors():
                field = " -> ".join(map(str, error["loc"]))
                error_msg = f"字段 '{field}': {error['msg']}"
                error_details.append(error_msg)
                
            validation_error = ConfigValidationError(
                message="配置验证失败"
            )
            validation_error.original_error = e
            
            self.logger.error("配置验证失败，请检查 `config.toml` 文件中的以下错误：")
            for detail in error_details:
                self.logger.error(f"  - {detail}")
            
            self.logger.log_custom_exception(validation_error)
            raise validation_error
        except tomllib.TOMLDecodeError as e:
            error = ConfigError(
                message=f"TOML解析错误: {str(e)}"
            )
            error.original_error = e
            self.logger.error(f"加载配置文件时发生TOML解析错误: {error.message}")
            self.logger.log_custom_exception(error)
            raise error
        except Exception as e:
            error = ConfigError(
                message=f"加载配置文件时发生未知错误: {str(e)}"
            )
            error.original_error = e
            self.logger.exception(f"加载配置文件时发生未知错误: {error.message}")
            self.logger.log_custom_exception(error)
            raise error

    def _check_file_permissions(self):
        """
        检查配置文件权限
        
        确保配置文件不会被其他用户读取，保护敏感信息。
        """
        if not self.path.exists():
            return
            
        try:
            import stat

            # 获取文件状态
            file_stat = self.path.stat()
            
            # 检查文件权限
            mode = file_stat.st_mode
            
            # 检查是否其他用户可读
            if mode & stat.S_IROTH:
                self.logger.warning(f"配置文件 {self.path} 其他用户可读，存在安全风险")
                self.logger.info("建议使用命令: chmod 600 config.toml")
            
            # 检查是否其他用户可写
            if mode & stat.S_IWOTH:
                self.logger.error(f"配置文件 {self.path} 其他用户可写，存在严重安全风险！")
                self.logger.error("请立即修复权限: chmod 600 config.toml")
                
        except Exception as e:
            self.logger.warning(f"检查文件权限失败: {e}")

    def _override_with_env_vars(self, raw_config: dict) -> dict:
        """
        使用环境变量覆盖敏感配置
        
        Args:
            raw_config: 原始配置字典
            
        Returns:
            更新后的配置字典
        """
        # MySQL 配置
        if 'mysql' in raw_config:
            mysql_config = raw_config['mysql']
            mysql_config['host'] = env_loader.get('MYSQL_HOST', mysql_config.get('host', 'localhost'))
            mysql_config['port'] = env_loader.get_int('MYSQL_PORT', mysql_config.get('port', 3306))
            mysql_config['user'] = env_loader.get('MYSQL_USER', mysql_config.get('user', 'root'))
            mysql_config['password'] = env_loader.get('MYSQL_PASSWORD', mysql_config.get('password', ''))
            mysql_config['db'] = env_loader.get('MYSQL_DB', mysql_config.get('db', 'neobot'))
        
        # Redis 配置
        if 'redis' in raw_config:
            redis_config = raw_config['redis']
            redis_config['host'] = env_loader.get('REDIS_HOST', redis_config.get('host', 'localhost'))
            redis_config['port'] = env_loader.get_int('REDIS_PORT', redis_config.get('port', 6379))
            redis_config['db'] = env_loader.get_int('REDIS_DB', redis_config.get('db', 0))
            redis_config['password'] = env_loader.get('REDIS_PASSWORD', redis_config.get('password', ''))
            redis_config['signing_secret'] = env_loader.get('REDIS_SIGNING_SECRET', redis_config.get('signing_secret', ''))
        
        # NapCat WebSocket 配置
        if 'napcat_ws' in raw_config:
            ws_config = raw_config['napcat_ws']
            ws_config['uri'] = env_loader.get('NAPCAT_WS_URI', ws_config.get('uri', 'ws://localhost:8080'))
            ws_config['token'] = env_loader.get('NAPCAT_WS_TOKEN', ws_config.get('token', ''))
        
        # Discord 配置
        if 'discord' in raw_config:
            discord_config = raw_config['discord']
            discord_config['token'] = env_loader.get('DISCORD_TOKEN', discord_config.get('token', ''))
            discord_config['proxy'] = env_loader.get('DISCORD_PROXY', discord_config.get('proxy'))
        
        # Bilibili 配置
        if 'bilibili' in raw_config:
            bili_config = raw_config['bilibili']
            bili_config['sessdata'] = env_loader.get('BILIBILI_SESSDATA', bili_config.get('sessdata'))
            bili_config['bili_jct'] = env_loader.get('BILIBILI_BILI_JCT', bili_config.get('bili_jct'))
            bili_config['buvid3'] = env_loader.get('BILIBILI_BUVID3', bili_config.get('buvid3'))
            bili_config['dedeuserid'] = env_loader.get('BILIBILI_DEDEUSERID', bili_config.get('dedeuserid'))
        
        # Douyin 配置
        if 'douyin' in raw_config:
            douyin_config = raw_config['douyin']
            douyin_config['api_key'] = env_loader.get('DOUYIN_API_KEY', douyin_config.get('api_key', ''))
            douyin_config['qzqi_api_key'] = env_loader.get('DOUYIN_QZQI_APIKEY', douyin_config.get('qzqi_api_key', ''))
        
        # Docker 配置
        if 'docker' in raw_config:
            docker_config = raw_config['docker']
            docker_config['base_url'] = env_loader.get('DOCKER_BASE_URL', docker_config.get('base_url'))
            docker_config['tls_verify'] = env_loader.get_bool('DOCKER_TLS_VERIFY', docker_config.get('tls_verify', False))
        
        # 反向 WebSocket 配置
        if 'reverse_ws' in raw_config:
            reverse_config = raw_config['reverse_ws']
            reverse_config['enabled'] = env_loader.get_bool('REVERSE_WS_ENABLED', reverse_config.get('enabled', False))
            reverse_config['host'] = env_loader.get('REVERSE_WS_HOST', reverse_config.get('host', '0.0.0.0'))
            reverse_config['port'] = env_loader.get_int('REVERSE_WS_PORT', reverse_config.get('port', 3002))
            reverse_config['token'] = env_loader.get('REVERSE_WS_TOKEN', reverse_config.get('token'))
        
        # 本地文件服务器配置
        if 'local_file_server' in raw_config:
            server_config = raw_config['local_file_server']
            server_config['enabled'] = env_loader.get_bool('LOCAL_FILE_SERVER_ENABLED', server_config.get('enabled', True))
            server_config['host'] = env_loader.get('LOCAL_FILE_SERVER_HOST', server_config.get('host', '0.0.0.0'))
            server_config['port'] = env_loader.get_int('LOCAL_FILE_SERVER_PORT', server_config.get('port', 3003))
            server_config['base_url'] = env_loader.get('LOCAL_FILE_SERVER_BASE_URL', server_config.get('base_url', ''))
        
        # 日志配置
        if 'logging' in raw_config:
            log_config = raw_config['logging']
            log_config['level'] = env_loader.get('LOG_LEVEL', log_config.get('level', 'DEBUG'))
            log_config['file_level'] = env_loader.get('LOG_FILE_LEVEL', log_config.get('file_level', 'DEBUG'))
            log_config['console_level'] = env_loader.get('LOG_CONSOLE_LEVEL', log_config.get('console_level', 'INFO'))
        
        return raw_config

    def _generate_example_config(self):
        """
        生成示例配置文件
        """
        example_path = Path("config.example.toml")
        
        if not example_path.exists():
            self.logger.error(f"示例配置文件 {example_path} 不存在，无法生成配置")
            raise ConfigNotFoundError(message=f"示例配置文件 {example_path} 不存在")
        
        content = example_path.read_text()
        self.path.write_text(content)

    # 通过属性访问配置
    @property
    def napcat_ws(self) -> NapCatWSModel:
        """
        获取 NapCat WebSocket 配置
        """
        return self._model.napcat_ws

    @property
    def bot(self) -> BotModel:
        """
        获取 Bot 基础配置
        """
        return self._model.bot

    @property
    def redis(self) -> RedisModel:
        """
        获取 Redis 配置
        """
        return self._model.redis
    
    @property
    def mysql(self) -> MySQLModel:
        """
        获取 MySQL 配置
        """
        return self._model.mysql

    @property
    def docker(self) -> DockerModel:
        """
        获取 Docker 配置
        """
        return self._model.docker
    
    @property
    def image_manager(self) -> ImageManagerModel:
        """
        获取图片生成管理器配置
        """
        return self._model.image_manager

    @property
    def reverse_ws(self) -> ReverseWSModel:
        """
        获取反向 WebSocket 配置
        """
        return self._model.reverse_ws
    
    @property
    def threading(self) -> ThreadingModel:
        """
        获取线程管理配置
        """
        return self._model.threading
    
    @property
    def bilibili(self) -> BilibiliModel:
        """
        获取 Bilibili 配置
        """
        return self._model.bilibili
    
    @property
    def local_file_server(self) -> LocalFileServerModel:
        """
        获取本地文件服务器配置
        """
        return self._model.local_file_server

    @property
    def discord(self) -> DiscordModel:
        """
        获取 Discord 配置
        """
        return self._model.discord
    
    @property
    def cross_platform(self) -> CrossPlatformModel:
        """
        获取跨平台配置
        """
        return self._model.cross_platform
    
    @property
    def logging(self) -> LoggingModel:
        """
        获取日志配置
        """
        return self._model.logging

    @property
    def mcc_adapter(self) -> McCAdapterModel:
        """
        获取 MCC 适配器配置
        """
        return self._model.mcc_adapter

    @property
    def douyin(self) -> DouyinModel:
        """
        获取抖音解析配置
        """
        return self._model.douyin

    @property
    def jinman(self) -> JinmanModel:
        """
        获取禁漫天堂（JMComic）配置
        """
        return self._model.jinman

    @property
    def divingfish(self) -> DivingFishModel:
        """
        获取水鱼查分器（diving-fish）配置
        """
        return self._model.divingfish

    @property
    def ehentai(self) -> EhentaiModel:
        """
        获取 E-Hentai 解析配置
        """
        return self._model.ehentai


# 实例化全局配置对象
global_config = Config()
