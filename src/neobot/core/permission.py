from enum import Enum
from functools import total_ordering


@total_ordering
class Permission(Enum):
    """
    定义用户权限等级的枚举类。

    使用 @total_ordering 装饰器，只需定义 __lt__ 和 __eq__，
    即可自动实现所有比较运算符。
    """
    USER = "user"
    OP = "op"
    ADMIN = "admin"

    @property
    def _level_map(self):
        """
        内部属性，用于映射枚举成员到整数等级。
        """
        return {
            Permission.USER: 1,
            Permission.OP: 2,
            Permission.ADMIN: 3
        }

    def __lt__(self, other):
        """
        比较当前权限是否小于另一个权限。
        """
        if not isinstance(other, Permission):
            return NotImplemented
        return self._level_map[self] < self._level_map[other]

    def __ge__(self, other):
        """
        比较当前权限是否大于等于另一个权限。
        """
        if not isinstance(other, Permission):
            return NotImplemented
        return self._level_map[self] >= self._level_map[other]
