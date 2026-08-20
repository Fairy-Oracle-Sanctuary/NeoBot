"""
Pydantic 配置模型模块

该模块使用 Pydantic 定义了与 `config.toml` 文件结构完全对应的配置模型。
这使得配置的加载、校验和访问都变得类型安全和健壮。
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class NapCatWSModel(BaseModel):
    """
    对应 `config.toml` 中的 `[napcat_ws]` 配置块。
    """
    uri: str
    token: str = ""
    reconnect_interval: int = 5


class BotModel(BaseModel):
    """
    对应 `config.toml` 中的 `[bot]` 配置块。
    """
    command: List[str] = Field(default_factory=lambda: ["/"])
    ignore_self_message: bool = True
    permission_denied_message: str = "权限不足，需要 {permission_name} 权限"

class ReverseWSModel(BaseModel):
    """
    对应 `config.toml` 中的 `[reverse_ws]` 配置块。
    """
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 3002
    token: Optional[str] = None


class RedisModel(BaseModel):
    """
    对应 `config.toml` 中的 `[redis]` 配置块。
    """
    host: str
    port: int
    db: int
    password: str
    signing_secret: str = ""  # pubsub 消息 HMAC 签名密钥；留空则回退到 password


class MySQLModel(BaseModel):
    """
    对应 `config.toml` 中的 `[mysql]` 配置块。
    """
    host: str
    port: int
    user: str
    password: str
    db: str
    charset: str = "utf8mb4"
    


class DockerModel(BaseModel):
    """
    对应 `config.toml` 中的 `[docker]` 配置块。
    """
    base_url: Optional[str] = None
    sandbox_image: str = "python-sandbox:latest"
    timeout: int = 10
    concurrency_limit: int = 5
    tls_verify: bool = False
    ca_cert_path: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None

class ImageManagerModel(BaseModel):
    """
    对应 `config.toml` 中的 `[image_manager]` 配置块。
    """
    image_height: int = 1920
    image_width: int = 1080


class ThreadingModel(BaseModel):
    """
    对应 `config.toml` 中的 `[threading]` 配置块。
    """
    max_workers: int = Field(default=10, ge=1, le=100)
    client_max_workers: int = Field(default=5, ge=1, le=50)
    thread_name_prefix: str = "NeoBot-Thread"


class BilibiliModel(BaseModel):
    """
    对应 `config.toml` 中的 `[bilibili]` 配置块。
    """
    sessdata: Optional[str] = None
    bili_jct: Optional[str] = None
    buvid3: Optional[str] = None
    dedeuserid: Optional[str] = None


class DouyinModel(BaseModel):
    """
    对应 `config.toml` 中的 `[douyin]` 配置块。
    """
    api_key: str = ""  # douyin2api 服务密钥（https://dy-api.d1ck.top），留空则跳过该解析通道
    qzqi_api_key: str = ""  # 远梦API（https://api.qzqi.com）DouYinVideo 接口密钥，留空则跳过该解析通道


class JinmanModel(BaseModel):
    """
    对应 `config.toml` 中的 `[jinman]` 配置块。

    禁漫天堂（JMComic）PDF 解析插件使用的自建 JMComic-Api 服务配置。
    服务仓库：https://github.com/FfmpegZZZ/JMComic-Api
    """
    api_base: str = "http://127.0.0.1:8699"  # JMComic-Api 服务地址
    timeout: int = 600  # PDF 生成超时（秒），首本生成需下载全部图片


class EhentaiModel(BaseModel):
    """
    对应 `config.toml` 中的 `[ehentai]` 配置块。

    E-Hentai / ExHentai 画廊解析插件使用的自建 RESTful-ehentai-api 服务配置。
    服务仓库：https://github.com/bandcomic/RESTful-ehentai-api
    """
    api_base: str = "http://127.0.0.1:8677"  # RESTful-ehentai-api 服务地址
    timeout: int = 30  # 画廊详情请求超时（秒）
    cookie: str = ""  # 可选：E-Hentai/ExHentai Cookie（访问 ExHentai 全部内容需要）


class LocalFileServerModel(BaseModel):
    """
    对应 `config.toml` 中的 `[local_file_server]` 配置块。
    """
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 3003
    # NapCat 等外部服务访问本文件服务器时使用的地址。
    # 留空时默认使用 http://127.0.0.1:{port}（适用于 NapCat 与 NeoBot 同机且 NapCat 为 host 网络）。
    # 若 NapCat 是独立容器，请配置为宿主机可达地址，如 http://<宿主机IP>:3003
    base_url: str = ""


class DiscordModel(BaseModel):
    """
    对应 `config.toml` 中的 `[discord]` 配置块。
    """
    enabled: bool = False
    token: str = ""
    proxy: Optional[str] = None
    proxy_type: str = "http"


class CrossPlatformMapping(BaseModel):
    """
    跨平台映射配置
    """
    qq_group_id: int
    name: str


class TranslationModel(BaseModel):
    """
    翻译配置
    """
    enabled: bool = True
    api_key: str = ""
    api_url: str = ""
    model: str = "deepseek-chat"


class CrossPlatformModel(BaseModel):
    """
    对应 `config.toml` 中的 `[cross_platform]` 配置块。
    """
    enabled: bool = False
    mappings: Optional[dict[int, CrossPlatformMapping]] = None
    translation: TranslationModel = Field(default_factory=TranslationModel)


class LoggingModel(BaseModel):
    """
    对应 `config.toml` 中的 `[logging]` 配置块。
    """
    level: str = "DEBUG"
    file_level: str = "DEBUG"
    console_level: str = "INFO"


class McCInstanceModel(BaseModel):
    """
    对应 `[mcc_adapter.instances]` 中的单个 MCC 实例配置。

    每个 MCC 机器人一个实例：角色名、MCP 端点、鉴权、可用群与触发词。
    """
    name: str = "default"
    role_name: str = ""
    enabled: bool = True
    url: str = "http://127.0.0.1:33333/mcp"
    auth_token: str = ""
    timeout_ms: int = 10000
    groups: List[int] = Field(default_factory=list)
    trigger_words: List[str] = Field(default_factory=lambda: ["luoxiaolei"])
    # 是否开放挂机点菜单/传送（挂机点为部分组织私有资源）
    afk_enabled: bool = True


class McCWikiModel(BaseModel):
    """
    对应 `[mcc_adapter.wiki]`：MCC Agent 的 DokuWiki 知识库（JSON-RPC API）。

    鉴权二选一：
    - token：Bearer token（优先）
    - username/password：先尝试 core.login 会话，失败时回退 HTTP Basic
    """
    enabled: bool = False
    base_url: str = "https://mcnnyy2.yyrain.cn/lib/exe/jsonrpc.php"
    username: str = ""
    password: str = ""
    token: str = ""
    timeout_ms: int = 10000


class McCMapModel(BaseModel):
    """
    对应 `[mcc_adapter.map]`：实时地图（BlueMap）数据源。

    - players.json：在线玩家列表（含坐标）
    - markers.json：服务器标记；folia-regions 的 detail 内含每个已加载区域的
      TPS / MSPT / 区块数 / 实体数 / 玩家数
    """
    enabled: bool = False
    base_url: str = "https://map.mgcraft.net"
    world: str = "world"
    cache_seconds: int = 30
    timeout_ms: int = 10000


class McCAdapterModel(BaseModel):
    """
    对应 `config.toml` 中的 `[mcc_adapter]` 配置块。

    MCC 能力已解耦到独立程序 mcc-service：本配置只包含服务端点与鉴权，
    实例列表由 mcc-service 的 /api/instances 提供。

    neobot 仅保留两项职责：
    1. 签发登录密钥（私聊"登录" → POST /api/auth/issue，走 panel_token 鉴权）
    2. 只读 agent 查询服务器消息（/ag，走 service_token 鉴权，固定 public 实例）
    """
    enabled: bool = False
    service_url: str = "http://127.0.0.1:8800"
    # agent 查询用（管理员 token）
    service_token: str = ""
    # 签发登录密钥用（面板 token，POST /api/auth/issue）
    panel_token: str = ""
    timeout_ms: int = 10000
    listener_ignore_senders: List[str] = Field(default_factory=list)


class ConfigModel(BaseModel):
    """
    顶层配置模型，整合了所有子配置块。
    """
    napcat_ws: NapCatWSModel
    bot: BotModel
    redis: RedisModel
    mysql: MySQLModel
    docker: DockerModel
    image_manager: ImageManagerModel
    reverse_ws: ReverseWSModel
    threading: ThreadingModel = Field(default_factory=ThreadingModel)
    bilibili: BilibiliModel = Field(default_factory=BilibiliModel)
    douyin: DouyinModel = Field(default_factory=DouyinModel)
    jinman: JinmanModel = Field(default_factory=JinmanModel)
    ehentai: EhentaiModel = Field(default_factory=EhentaiModel)
    local_file_server: LocalFileServerModel = Field(default_factory=LocalFileServerModel)
    discord: DiscordModel = Field(default_factory=DiscordModel)
    cross_platform: CrossPlatformModel = Field(default_factory=CrossPlatformModel)
    logging: LoggingModel = Field(default_factory=LoggingModel)
    mcc_adapter: McCAdapterModel = Field(default_factory=McCAdapterModel)
