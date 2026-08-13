import os
import sys

def create_plugin(plugin_name):
    base = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.join(base, "../plugins")
    os.makedirs(plugin_dir, exist_ok=True)

    file_name = f"{plugin_name.lower()}.py"
    file_path = os.path.join(plugin_dir, file_name)

    if os.path.exists(file_path):
        print("插件已存在")
        return

    template = f'''from core.managers.command_manager import matcher
from core.bot import Bot
from models.events.message import MessageEvent
from core.permission import Permission

__plugin_meta__ = {{
    "name": "{plugin_name.lower()}",
    "description": "",
    "usage": ""
}}

@matcher.command("{plugin_name.lower()}")
async def _(bot: Bot, event: MessageEvent):
    pass
'''

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(template)

    print(f"插件创建成功：{file_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python create_plugin.py 插件名")
        sys.exit(1)
    create_plugin(sys.argv[1])
