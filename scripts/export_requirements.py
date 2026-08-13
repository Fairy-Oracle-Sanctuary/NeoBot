#!/usr/bin/env python3
"""
导出项目依赖到 requirements.txt 文件

支持两种模式：
1. 默认模式：导出当前虚拟环境中的所有包（pip freeze）
2. 本地模式：只导出当前项目的依赖（pip freeze --local）

使用方法:
    python export_requirements.py [options]

选项:
    --local, -l    只导出当前项目的依赖（推荐）
    --output, -o   指定输出文件路径（默认为 requirements.txt）
    --help, -h     显示帮助信息
"""
import subprocess
import sys
import argparse

def run_pip_freeze(local_mode=False):
    """
    运行 pip freeze 命令
    
    Args:
        local_mode: 是否只导出当前项目依赖
        
    Returns:
        (success, output): 成功标志和输出内容
    """
    cmd = ['pip', 'freeze']
    if local_mode:
        cmd.append('--local')
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = f"pip freeze 命令失败，退出码: {e.returncode}\n"
        if e.stderr:
            error_msg += f"错误信息: {e.stderr}"
        return False, error_msg
    except FileNotFoundError:
        return False, "错误: 未找到 pip 命令，请确保 Python 环境已正确安装"
    except Exception as e:
        return False, f"未知错误: {e}"

def write_requirements_file(output_path, content):
    """
    将依赖内容写入文件
    
    Args:
        output_path: 输出文件路径
        content: 依赖内容
        
    Returns:
        success: 是否成功
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 统计行数（忽略空行）
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        return True, len(lines)
    except IOError as e:
        return False, f"写入文件失败: {e}"
    except Exception as e:
        return False, f"未知错误: {e}"

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='导出项目依赖到 requirements.txt 文件')
    
    parser.add_argument('--local', '-l', action='store_true',
                       help='只导出当前项目的依赖（推荐）')
    parser.add_argument('--output', '-o', default='requirements.txt',
                       help='指定输出文件路径（默认为 requirements.txt）')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("NEO Bot 依赖导出工具")
    print("=" * 60)
    
    # 显示模式信息
    if args.local:
        print("模式: 本地模式（只导出当前项目依赖）")
    else:
        print("模式: 全局模式（导出所有已安装包）")
        print("提示: 建议使用 --local 选项只导出当前项目依赖")
    
    print(f"输出文件: {args.output}")
    print()
    
    # 运行 pip freeze
    print("正在收集依赖信息...")
    success, output = run_pip_freeze(args.local)
    
    if not success:
        print(f"错误: {output}")
        sys.exit(1)
    
    # 写入文件
    print("正在写入文件...")
    success, result = write_requirements_file(args.output, output)
    
    if not success:
        print(f"错误: {result}")
        sys.exit(1)
    
    line_count = result
    print("✓ 依赖导出完成")
    print(f"  文件: {args.output}")
    print(f"  依赖数量: {line_count} 个包")
    
    # 显示前几个依赖（如果有）
    lines = [line.strip() for line in output.split('\n') if line.strip()]
    if lines:
        print("\n前5个依赖:")
        for i, line in enumerate(lines[:5], 1):
            print(f"  {i}. {line}")
        if len(lines) > 5:
            print(f"  ... 还有 {len(lines) - 5} 个依赖")
    
    print("\n" + "=" * 60)
    print("提示: 可以使用 pip install -r requirements.txt 安装这些依赖")
    print("=" * 60)

if __name__ == '__main__':
    main()