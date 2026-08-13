from neobot.core.managers import command_manager, permission_manager
from neobot.core.permission import Permission
from neobot.models.events.message import MessageEvent

# 更新插件元信息以包含OP管理
__plugin_meta__ = {
    "name": "权限管理",
    "description": "管理机器人的管理员和操作员",
    "usage": (
        "/admin list - 列出所有管理员和操作员\n"
        "/admin add_admin <QQ号> - 添加管理员\n"
        "/admin remove_admin <QQ号> - 移除管理员\n"
        "/admin add_op <QQ号> - 添加操作员\n"
        "/admin remove_op <QQ号> - 移除操作员"
    ),
}


@command_manager.command("admin", permission=Permission.ADMIN)
async def admin_management(event: MessageEvent, args: list[str]):
    """
    处理所有权限管理相关的命令。
    """
    parts = args
    if not parts:
        await event.reply(f"用法不正确。\n\n{__plugin_meta__['usage']}")
        return

    subcommand = parts[0].lower()

    if subcommand == "list":
        await list_permissions(event)
        return

    # 处理需要QQ号的命令
    if len(parts) < 2 or not parts[1].isdigit():
        await event.reply(f"请提供有效的用户QQ号。\n用法: /admin {subcommand} <QQ号>")
        return

    try:
        target_user_id = int(parts[1])
    except ValueError:
        await event.reply("无效的QQ号。")
        return

    # 安全检查
    if target_user_id == event.user_id:
        await event.reply("你不能操作自己的权限。")
        return
    if target_user_id == event.self_id:
        await event.reply("你不能操作机器人自身的权限。")
        return

    # 根据子命令分发
    if subcommand == "add_admin":
        await permission_manager.set_user_permission(target_user_id, Permission.ADMIN)
        await event.reply(f"已成功添加管理员：{target_user_id}")
    elif subcommand == "remove_admin":
        await permission_manager.set_user_permission(target_user_id, Permission.USER)
        await event.reply(f"已成功移除管理员：{target_user_id}")
    elif subcommand == "add_op":
        await permission_manager.set_user_permission(target_user_id, Permission.OP)
        await event.reply(f"已成功添加操作员：{target_user_id}")
    elif subcommand == "remove_op":
        await permission_manager.set_user_permission(target_user_id, Permission.USER)
        await event.reply(f"已成功移除操作员：{target_user_id}")
    else:
        await event.reply(f"未知的子命令 '{subcommand}'。\n\n{__plugin_meta__['usage']}")


async def list_permissions(event: MessageEvent):
    """
    列出所有具有特殊权限（管理员和操作员）的用户。
    """
    permissions = await permission_manager.get_all_user_permissions()
    if not permissions:
        await event.reply("当前没有配置任何特殊权限的用户。")
        return

    admins = {uid for uid, p in permissions.items() if p == 'admin'}
    ops = {uid for uid, p in permissions.items() if p == 'op'}

    reply_msg = "当前权限列表：\n"
    if admins:
        reply_msg += "--- 管理员 ---\n"
        for user_id in admins:
            reply_msg += f"- {user_id}\n"
    if ops:
        reply_msg += "--- 操作员 ---\n"
        for user_id in ops:
            reply_msg += f"- {user_id}\n"

    await event.reply(reply_msg.strip())
