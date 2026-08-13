import aiomysql
from ..config_loader import global_config as config
from ..utils.logger import logger
from ..utils.singleton import Singleton


class MySQLManager(Singleton):
    """
    MySQL 数据库连接管理器（异步单例）
    """
    _pool = None

    def __init__(self):
        """
        初始化 MySQL 管理器
        """
        super().__init__()

    async def initialize(self):
        """
        异步初始化 MySQL 连接池并进行健康检查
        """
        if self._pool is None:
            try:
                mysql_config = config.mysql
                host = mysql_config.host
                port = mysql_config.port
                user = mysql_config.user
                password = mysql_config.password
                db = mysql_config.db
                charset = mysql_config.charset

                # 空密码加固：明确警告，防止弱凭证配置被忽视
                if not password:
                    logger.warning(
                        f"[MySQL] 数据库 {user}@{host}:{port} 未配置密码（空凭证），"
                        "存在被未授权访问的风险，建议为 MySQL 设置强密码并限制访问来源"
                    )

                logger.info(f"正在尝试连接 MySQL: {host}:{port}, DB: {db}")

                self._pool = await aiomysql.create_pool(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    db=db,
                    charset=charset,
                    autocommit=False,
                    maxsize=10,
                    minsize=1
                )

                async with self._pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                        result = await cur.fetchone()
                        if result and result[0] == 1:
                            logger.success("MySQL 连接成功！")
                        else:
                            logger.error("MySQL 连接失败: 健康检查失败")
            except Exception as e:
                logger.exception(f"MySQL 初始化时发生未知错误: {e}")
                self._pool = None

    @property
    def pool(self):
        """
        获取 MySQL 连接池实例
        """
        if self._pool is None:
            raise ConnectionError("MySQL 未初始化或连接失败，请先调用 initialize()")
        return self._pool

    async def execute(self, sql: str, args: tuple = None):
        """
        执行 SQL 语句（用于 INSERT、UPDATE、DELETE）

        Args:
            sql: SQL 语句
            args: 参数元组

        Returns:
            影响的行数
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)
                await conn.commit()
                return cur.rowcount

    async def fetchone(self, sql: str, args: tuple = None):
        """
        查询单条记录

        Args:
            sql: SQL 语句
            args: 参数元组

        Returns:
            单条记录字典
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchone()

    async def fetchall(self, sql: str, args: tuple = None):
        """
        查询多条记录

        Args:
            sql: SQL 语句
            args: 参数元组

        Returns:
            记录列表
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchall()

    async def begin_transaction(self):
        """
        开始事务

        Returns:
            事务连接对象
        """
        conn = await self._pool.acquire()
        return conn

    async def commit_transaction(self, conn):
        """
        提交事务

        Args:
            conn: 事务连接对象
        """
        await conn.commit()
        await self._pool.release(conn)

    async def rollback_transaction(self, conn):
        """
        回滚事务

        Args:
            conn: 事务连接对象
        """
        await conn.rollback()
        await self._pool.release(conn)


mysql_manager = MySQLManager()
