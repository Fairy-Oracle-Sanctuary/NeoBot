"""
通用单例模式基类
"""
from typing import Any, Dict, Optional, Type, TypeVar, cast

T = TypeVar('T')

# 存储每个类的实例
_instance_store: Dict[Type, Any] = {}

class Singleton:
    """
    一个通用的单例基类

    任何继承自该类的子类都将自动成为单例。
    它通过重写 __new__ 方法来确保每个类只有一个实例。
    同时，它处理了重复初始化的问题，确保 __init__ 方法只在第一次实例化时被调用。
    """
    _initialized: bool = False

    def __new__(cls: Type[T], *args: Any, **kwargs: Any) -> T:
        """
        创建或返回现有的实例

        Args:
            *args: 传递给构造函数的位置参数
            **kwargs: 传递给构造函数的关键字参数

        Returns:
            T: 单例实例
        """
        # 使用全局字典存储实例，修复类型检查问题
        if cls not in _instance_store:
            _instance_store[cls] = super(Singleton, cls).__new__(cls)
        return _instance_store[cls]

    def __init__(self) -> None:
        """
        确保初始化逻辑只执行一次
        """
        if self._initialized:
            return
        self._initialized = True


def singleton(cls: Type[T]) -> Type[T]:
    """
    单例装饰器
    
    将普通类转换为单例类，确保整个应用程序中只有一个实例。
    
    Args:
        cls: 要转换为单例的类
    
    Returns:
        Type[T]: 单例类
    """
    # 为每个装饰的类创建一个实例存储
    class_instance: Optional[T] = None
    
    # 创建一个新的类，继承自原始类
    class SingletonClass(cls):
        """单例包装类"""
        
        def __new__(cls: Type[T], *args: Any, **kwargs: Any) -> T:
            """创建或返回现有的实例"""
            nonlocal class_instance
            if class_instance is None:
                # 使用super()调用原始类的__new__方法
                class_instance = super(SingletonClass, cls).__new__(cls)
            return class_instance
    
    # 复制类的元数据
    SingletonClass.__name__ = cls.__name__
    SingletonClass.__doc__ = cls.__doc__
    SingletonClass.__module__ = cls.__module__
    
    return SingletonClass
