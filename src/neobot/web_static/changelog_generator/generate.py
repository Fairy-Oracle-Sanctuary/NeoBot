import os
import sys
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# ==========================================
# 配置区域
# ==========================================

# 输出文件路径 (相对于当前脚本或绝对路径)
OUTPUT_FILE = "../changelog.html"

# 更新日志数据
# 格式说明：
# version: 版本号
# date: 日期 (YYYY-MM-DD)
# description: 版本描述 (可选)
# changes: 变更列表
#   - type: 类型 (add, update, fix)
#   - content: 变更内容
changelogs = [
    {
        "version": "v1.0.1",
        "date": "2026-3-1",
        "description": "后端修正。",
        "changes": [
            {"type": "add", "content": "天气查询功能美化"},
            {"type": "fix", "content": "b站的视频解析已修复，感谢Nemo2011的bilibili-api python库，采用GPL3.0开源"},
            {"type": "add", "content": "python3.14的自由线程测试已开启"},
            {"type": "update", "content": "镜像图片功能现已可以转换动态表情包"}
            
            
        ]
    }
]

# ==========================================
# 生成逻辑 (通常不需要修改)
# ==========================================

def generate_changelog():
    # 获取当前脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 设置 Jinja2 环境
    env = Environment(loader=FileSystemLoader(base_dir))
    template = env.get_template("template.html")
    
    # 获取最新版本号
    latest_version = changelogs[0]["version"] if changelogs else "v0.0.0"
    
    # 渲染模板
    html_content = template.render(
        log=changelogs[0] if changelogs else None,
        latest_version=latest_version,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    # 确定输出路径
    output_path = os.path.join(base_dir, OUTPUT_FILE)
    
    # 写入文件
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"✅ 成功生成更新日志: {os.path.abspath(output_path)}")
    except Exception as e:
        print(f"❌ 生成失败: {e}")

if __name__ == "__main__":
    generate_changelog()
