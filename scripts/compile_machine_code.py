#!/usr/bin/env python3
"""
自动化跨平台 Python 模块编译脚本 (v2.2)

将核心 Python 模块编译为机器码 (.pyd 或 .so) 以提升性能。
此版本实现了全自动清理和保守的编译范围，以确保稳定性。

支持的平台：
- Windows: 生成 .pyd 文件
- Linux: 生成 .so 文件

使用方法:
    python scripts/compile_machine_code.py

脚本会自动执行以下步骤:
    1. 清理所有旧的编译文件 (.pyd, .so) 和 build 目录。
    2. 编译模块列表中所有兼容的模块。
    3. 列出所有成功编译的模块。

注意：
    1. 需要安装 C 编译器 (Windows 上需要 Visual Studio Build Tools, Linux 上需要 GCC)
    2. 需要安装 mypyc: pip install mypyc
    3. 编译后的文件是平台相关的，不能跨平台复制。
"""
import os
import sys
import glob
import subprocess
import shutil

# --- 配置区 ---

# 检测当前平台和 Python 版本
PLATFORM = sys.platform
PYTHON_VERSION = f"{sys.version_info.major}{sys.version_info.minor}"

if PLATFORM.startswith('win'):
    EXTENSION = '.pyd'
    BUILD_PREFIX = f'cp{PYTHON_VERSION}-win_amd64'
    BUILD_PATH = os.path.join('build', f'lib.win-amd64-cpython-{PYTHON_VERSION}')
elif PLATFORM.startswith('linux'):
    EXTENSION = '.so'
    BUILD_PREFIX = f'cp{PYTHON_VERSION}-x86_64-linux-gnu'
    BUILD_PATH = os.path.join('build', f'lib.linux-x86_64-cpython-{PYTHON_VERSION}')
else:
    print(f"不支持的平台: {PLATFORM}")
    sys.exit(1)

# 经过测试的稳定编译模块列表
MODULES = [
    # 工具模块
    'core/utils/executor.py',
    'core/utils/exceptions.py',
    'core/utils/logger.py',
    
    # 核心基础模块
    'core/ws.py',
    'core/config_loader.py',
    
    # 数据模型 (仅包含安全的、无复杂元类的部分)
    'models/message.py',
    'models/sender.py',
    'models/objects.py',
]

# --- 功能函数 ---

def list_compiled_modules():
    """列出已编译的模块"""
    print(f"\n已编译的 {PLATFORM} 模块:")
    print("=" * 50)
    
    compiled_files = glob.glob(f'**/*{EXTENSION}', recursive=True)
    compiled_files = [f for f in compiled_files if 'venv' not in f and '.venv' not in f]
    
    if compiled_files:
        for f in sorted(compiled_files):
            try:
                size = os.path.getsize(f) // 1024
                print(f"{f} ({size} KB)")
            except FileNotFoundError:
                continue
    else:
        print(f"未找到已编译的 {EXTENSION} 文件")
    
    print(f"\n总计: {len(compiled_files)} 个文件")

def clean_compiled_files():
    """清理所有编译生成的文件和目录"""
    print("--- 步骤 1: 清理旧的编译文件 ---")
    
    compiled_files = glob.glob(f'**/*{EXTENSION}', recursive=True)
    compiled_files = [f for f in compiled_files if 'venv' not in f and '.venv' not in f]
    
    if compiled_files:
        for f in sorted(compiled_files):
            try:
                os.remove(f)
                print(f"  已删除: {f}")
            except Exception as e:
                print(f"  删除失败 {f}: {e}")
    else:
        print("  没有可清理的文件")
        
    if os.path.exists('build'):
        try:
            shutil.rmtree('build')
            print("  已删除 build 目录")
        except Exception as e:
            print(f"  删除 build 目录失败: {e}")
    print("-" * 35)

def compile_module(module_path):
    """编译单个模块"""
    print(f"\n编译: {module_path}")
    
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'mypyc', module_path],
            capture_output=True,
            check=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # 智能查找编译产物
        base_name = os.path.basename(module_path).replace('.py', '')
        search_pattern = os.path.join(BUILD_PATH, '**', f'{base_name}.*{EXTENSION}')
        
        found_files = glob.glob(search_pattern, recursive=True)
        
        if found_files:
            build_module_path = found_files[0]
            dest_path = os.path.join(os.path.dirname(module_path), os.path.basename(build_module_path))
            
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(build_module_path, dest_path)
            print(f"  ✓ 编译成功: {dest_path}")
            return True
        else:
            print(f"  ✗ 编译失败：在 {BUILD_PATH} 中找不到编译产物")
            if result.stdout: print(f"  输出: {result.stdout[:500]}...")
            if result.stderr: print(f"  错误: {result.stderr[:500]}...")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"  ✗ 编译失败 (Exit Code: {e.returncode})")
        if e.stdout: print(f"  输出: {e.stdout[:500]}...")
        if e.stderr: print(f"  错误: {e.stderr[:500]}...")
        return False
    except Exception as e:
        print(f"  ✗ 编译时发生意外错误: {e}")
        return False

def compile_all_modules():
    """编译所有指定的模块"""
    print("\n--- 步骤 2: 开始编译模块 ---")
    
    valid_modules = []
    for module in MODULES:
        if os.path.exists(module):
            valid_modules.append(module)
        else:
            print(f"警告: 模块 {module} 不存在，已跳过")
            
    print(f"\n找到 {len(valid_modules)} 个有效模块进行编译。")
    
    success_count = 0
    failed_modules = []
    
    for module in valid_modules:
        if compile_module(module):
            success_count += 1
        else:
            failed_modules.append(module)
    
    print("\n" + "=" * 50)
    print(f"编译完成: {success_count}/{len(valid_modules)} 个模块成功")
    
    if failed_modules:
        print(f"失败模块: {failed_modules}")
        print("✗ 部分模块编译失败")
    else:
        print("✓ 所有模块编译成功")
    print("=" * 50)

def main():
    """主函数：执行清理、编译和列出结果的全过程"""
    if not (sys.version_info.major == 3 and sys.version_info.minor >= 8):
        print("警告: 推荐使用 Python 3.8+ 以获得最佳性能。")
    
    try:
        import mypyc
    except ImportError:
        print("错误: 未安装 mypyc，请运行: pip install mypyc")
        sys.exit(1)
        
    clean_compiled_files()
    compile_all_modules()
    list_compiled_modules()

if __name__ == '__main__':
    main()
