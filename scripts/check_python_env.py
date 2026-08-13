#!/usr/bin/env python3
"""
Python 环境检查脚本

检查当前 Python 环境是否符合 NEO Bot 要求，包括版本、GIL 状态、JIT 支持等。
"""
import sys
import platform

def main():
    """主函数"""
    print("=" * 60)
    print("NEO Bot Python 环境检查")
    print("=" * 60)
    
    # 1. Python 版本信息
    version_info = sys.version_info
    print("\n[1] Python 版本:")
    print(f"    版本号: {sys.version}")
    print(f"    主版本: {version_info.major}.{version_info.minor}.{version_info.micro}")
    print(f"    发布日期: {version_info.releaselevel} {version_info.serial}")
    
    # 检查是否为 Python 3.14
    if version_info.major == 3 and version_info.minor == 14:
        print("    ✓ 符合要求: Python 3.14")
    else:
        print(f"    ⚠ 警告: 推荐使用 Python 3.14，当前为 {version_info.major}.{version_info.minor}")
    
    # 2. 平台信息
    print("\n[2] 平台信息:")
    print(f"    操作系统: {platform.system()} {platform.release()}")
    print(f"    处理器: {platform.processor()}")
    print(f"    架构: {platform.machine()}")
    
    # 3. GIL 状态
    print("\n[3] GIL (全局解释器锁) 状态:")
    try:
        # Python 3.13+ free-threading build 才有这个属性
        is_gil_enabled = sys._is_gil_enabled()
        if is_gil_enabled:
            print("    GIL 已启用 (传统模式)")
        else:
            print("    GIL 已禁用 (自由线程模式)")
    except AttributeError:
        print("    GIL 状态: 未知 (sys._is_gil_enabled 未找到，可能是传统 GIL 构建)")
    
    # 4. JIT 状态
    print("\n[4] JIT (即时编译) 状态:")
    
    # 检查是否启用了 JIT
    jit_enabled = False
    jit_details = "未知"
    
    # 方法1: 检查启动标志
    if hasattr(sys, 'flags'):
        # Python 3.14 的 JIT 通过 -X jit 启用
        # 但 sys.flags 中没有直接的 JIT 标志
        pass
    
    # 方法2: 检查是否有 JIT 相关属性
    try:
        # 尝试导入 _jit 模块（如果存在）
        import _jit
        jit_enabled = True
        jit_details = "检测到 _jit 模块"
        del _jit  # 避免未使用的导入警告
    except ImportError:
        # 检查 sys 模块中是否有 JIT 相关属性
        if hasattr(sys, '_jit_enabled'):
            jit_enabled = sys._jit_enabled
            jit_details = f"sys._jit_enabled = {jit_enabled}"
        else:
            jit_details = "未检测到 JIT 模块或属性"
    
    if jit_enabled:
        print("    ✓ JIT 已启用")
        print(f"    详情: {jit_details}")
    else:
        print("    ⚠ JIT 未启用或不可用")
        print(f"    详情: {jit_details}")
        print("    建议: 启动时使用 -X jit 参数启用 JIT，例如: python -X jit main.py")
    
    # 5. 其他信息
    print("\n[5] 其他信息:")
    print(f"    实现: {platform.python_implementation()}")
    print(f"    构建: {platform.python_build()}")
    print(f"    编译器: {platform.python_compiler()}")
    
    # 6. 路径信息
    print("\n[6] 路径信息:")
    print(f"    执行文件: {sys.executable}")
    print(f"    前缀: {sys.prefix}")
    print("    路径:")
    for i, path in enumerate(sys.path[:5], 1):  # 只显示前5个
        print(f"      {i}. {path}")
    if len(sys.path) > 5:
        print(f"      ... 还有 {len(sys.path) - 5} 个路径")
    
    print("\n" + "=" * 60)
    print("检查完成")
    print("=" * 60)

if __name__ == '__main__':
    main()