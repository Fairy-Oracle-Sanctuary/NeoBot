"""
消息段模型模块

该模块定义了 `MessageSegment` 类，用于构建和表示 OneBot v11 协议中的消息段。
通过此类，可以方便地创建文本、图片、At 等不同类型的消息内容，并支持链式操作。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, List


@dataclass(slots=True)
class MessageSegment:
    """
    表示一个 OneBot v11 消息段。

    Attributes:
        type (str): 消息段的类型，例如 'text', 'image', 'at'。
        data (Dict[str, Any]): 消息段的具体数据，是一个键值对字典。
    """

    type: str
    data: Dict[str, Any]

    @property
    def plain_text(self) -> str:
        """
        当消息段类型为 'text' 时，快速获取其文本内容。

        Returns:
            str: 消息段的文本内容。如果类型不是 'text'，则返回空字符串。
        """
        return self.data.get("text", "") if self.type == "text" else ""

    @staticmethod
    def text(text: str) -> "MessageSegment":
        """
        创建一个文本消息段。

        Args:
            text (str): 文本内容。

        Returns:
            MessageSegment: 一个类型为 'text' 的消息段对象。
        """
        return MessageSegment(type="text", data={"text": text})

    @property
    def image_url(self) -> str:
        """
        当消息段类型为 'image' 时，快速获取其图片 URL。

        Returns:
            str: 图片的 URL。如果类型不是 'image' 或数据中不含 'url'，则返回空字符串。
        """
        return self.data.get("url", "") if self.type == "image" else ""

    @property
    def share_url(self) -> str:
        """
        当消息段类型为 'share' 时，快速获取其分享 URL。

        Returns:
            str: 分享的 URL。如果类型不是 'share' 或数据中不含 'url'，则返回空字符串。
        """
        return self.data.get("url", "") if self.type == "share" else ""

    @property
    def music_url(self) -> str:
        """
        当消息段类型为 'music' 且为 'custom' 类型时，快速获取其 URL。

        Returns:
            str: 音乐的 URL。如果类型不匹配，则返回空字符串。
        """
        if self.type == "music" and self.data.get("type") == "custom":
            return self.data.get("url", "")
        return ""

    @property
    def file_url(self) -> str:
        """
        当消息段类型为 'record', 'video', 'file' 时，快速获取其文件 URL。

        Returns:
            str: 文件的 URL 或路径。如果类型不匹配，则返回空字符串。
        """
        if self.type in ("record", "video", "file"):
            return self.data.get("file", "")
        return ""

    def is_at(self, user_id: Optional[int] = None) -> bool:
        """
        检查当前消息段是否是一个 'at' (提及) 消息段。

        Args:
            user_id (int, optional): 如果提供，则进一步检查被提及的 QQ 号是否匹配。
                                     Defaults to None.

        Returns:
            bool: 如果消息段是 'at' 类型且 user_id 匹配 (如果提供)，则返回 True。
        """
        if self.type != "at":
            return False
        if user_id is None:
            return True
        return str(self.data.get("qq")) == str(user_id)

    def __str__(self):
        """
        返回消息段的 CQ 码字符串表示。
        """
        if self.type == "text":
            return self.data.get("text", "")
        
        params = ",".join([f"{k}={v}" for k, v in self.data.items()])
        if params:
            return f"[CQ:{self.type},{params}]"
        return f"[CQ:{self.type}]"

    def __repr__(self):
        """
        返回消息段对象的字符串表示形式，便于调试。
        """
        return f"[MS:{self.type}:{self.data}]"

    def __add__(self, other: Any) -> "List[MessageSegment]":
        """
        支持消息段相加，返回消息段列表。
        """
        if isinstance(other, MessageSegment):
            return [self, other]
        elif isinstance(other, str):
            return [self, MessageSegment.text(other)]
        elif isinstance(other, list):
            return [self] + other
        return NotImplemented

    def __radd__(self, other: Any) -> "List[MessageSegment]":
        """
        支持反向相加。
        """
        if isinstance(other, MessageSegment):
            return [other, self]
        elif isinstance(other, str):
            return [MessageSegment.text(other), self]
        elif isinstance(other, list):
            return other + [self]
        return NotImplemented

    # --- 快捷构造方法 ---

    @staticmethod
    def from_text(text: str) -> "MessageSegment":
        """
        创建一个文本消息段。

        Args:
            text (str): 文本内容。

        Returns:
            MessageSegment: 一个类型为 'text' 的消息段对象。
        """
        return MessageSegment(type="text", data={"text": text})

    @staticmethod
    def at(user_id: int | str, name: Optional[str] = None) -> "MessageSegment":
        """
        创建一个 @某人 的消息段。

        Args:
            user_id (int | str): 要提及的 QQ 号。若为 "all"，则表示 @全体成员。
            name (str, optional): 当在群中找不到对应的QQ号时，显示的名称。Defaults to None.

        Returns:
            MessageSegment: 一个类型为 'at' 的消息段对象。
        """
        data = {"qq": str(user_id)}
        if name:
            data["name"] = name
        return MessageSegment(type="at", data=data)

    @staticmethod
    def image(file: str, image_type: Optional[str] = None, cache: bool = True, proxy: bool = True, timeout: Optional[int] = None, sub_type: Optional[int] = None) -> "MessageSegment":
        """
        创建一个图片消息段。

        Args:
            file (str): 图片的路径、URL 或 Base64 编码的字符串。
            image_type (str, optional): 图片类型，'flash' 表示闪照。Defaults to None.
            cache (bool, optional): 是否使用缓存。Defaults to True.
            proxy (bool, optional): 是否通过代理下载。Defaults to True.
            timeout (int, optional): 下载超时时间（秒）。Defaults to None.
            sub_type (int, optional): 图片子类型，用于特殊图片。Defaults to None.

        Returns:
            MessageSegment: 一个类型为 'image' 的消息段对象。
        """
        data = {"file": file, "cache": "1" if cache else "0", "proxy": "1" if proxy else "0"}
        if image_type:
            data["type"] = image_type
        if timeout:
            data["timeout"] = str(timeout)
        if sub_type:
            data["subType"] = str(sub_type)
        return MessageSegment(type="image", data=data)

    @staticmethod
    def face(id: int) -> "MessageSegment":
        """
        创建一个 QQ 表情消息段。

        Args:
            id (int): QQ 表情的 ID。

        Returns:
            MessageSegment: 一个类型为 'face' 的消息段对象。
        """
        return MessageSegment(type="face", data={"id": str(id)})

    @staticmethod
    def json(data: str) -> "MessageSegment":
        """
        创建一个 JSON 消息段。

        Args:
            data (str): JSON 字符串。

        Returns:
            MessageSegment: 一个类型为 'json' 的消息段对象。
        """
        return MessageSegment(type="json", data={"data": data})
    @staticmethod
    def xml(data: str) -> "MessageSegment":
        """
        创建一个 XML 消息段。

        Args:
            data (str): XML 字符串。

        Returns:
            MessageSegment: 一个类型为 'xml' 的消息段对象。
        """
        return MessageSegment(type="xml", data={"data": data})
    @staticmethod
    def share(url: str, title: str, content: Optional[str] = None, image: Optional[str] = None) -> "MessageSegment":
        """
        创建一个分享消息段。

        Args:
            url (str): 分享的 URL。
            title (str): 分享的标题。
            content (str, optional): 分享的描述内容。Defaults to None.
            image (str, optional): 分享的图片 URL。Defaults to None.

        Returns:
            MessageSegment: 一个类型为 'share' 的消息段对象。
        """
        data = {"url": url, "title": title}
        if content:
            data["content"] = content
        if image:
            data["image"] = image
        return MessageSegment(type="share", data=data)
    @staticmethod
    def music(type: str, id: str) -> "MessageSegment":
        """
        创建一个音乐消息段。

        Args:
            type (str): 音乐平台类型，如 "qq"、"xiami" 等。
            id (str): 音乐在平台上的唯一标识符。

        Returns:
            MessageSegment: 一个类型为 'music' 的消息段对象。
        """
        return MessageSegment(type="music", data={"type": type, "id": id})
    @staticmethod
    def music_custom(url: str, audio: str, title: str, content: Optional[str] = None, image: Optional[str] = None) -> "MessageSegment":
        """
        创建一个自定义音乐消息段。

        Args:
            url (str): 音乐的 URL。
            audio (str): 音乐的音频 URL。
            title (str): 音乐的标题。
            content (str, optional): 音乐的描述内容。Defaults to None.
            image (str, optional): 音乐的图片 URL。Defaults to None.

        Returns:
            MessageSegment: 一个类型为 'music_custom' 的消息段对象。
        """
        data = {"url": url, "audio": audio, "title": title}
        if content:
            data["content"] = content
        if image:
            data["image"] = image
        return MessageSegment(type="music", data={"type": "custom", **data})
    @staticmethod
    def record(file: str, magic: bool = False, cache: bool = True, proxy: bool = True, timeout: Optional[int] = None) -> "MessageSegment":
        """
        创建一个语音消息段。

        Args:
            file (str): 语音的路径、URL 或 Base64 编码的字符串。
            magic (bool, optional): 是否为变声。Defaults to False.
            cache (bool, optional): 是否使用缓存。Defaults to True.
            proxy (bool, optional): 是否通过代理下载。Defaults to True.
            timeout (int, optional): 下载超时时间（秒）。Defaults to None.

        Returns:
            MessageSegment: 一个类型为 'record' 的消息段对象。
        """
        data = {"file": file, "magic": "1" if magic else "0", "cache": "1" if cache else "0", "proxy": "1" if proxy else "0"}
        if timeout:
            data["timeout"] = str(timeout)
        return MessageSegment(type="record", data=data)
    @staticmethod
    def video(file: str, cover: Optional[str] = None, c: int = 2) -> "MessageSegment":
        """
        创建一个视频消息段。

        Args:
            file (str): 视频的路径、URL 或 Base64 编码的字符串。
            cover (str, optional): 视频封面，支持http, file和base64。Defaults to None.
            c (int, optional): 下载线程数。Defaults to 2.

        Returns:
            MessageSegment: 一个类型为 'video' 的消息段对象。
        """
        data = {"file": file, "c": str(c)}
        if cover:
            data["cover"] = cover
        return MessageSegment(type="video", data=data)
    @staticmethod
    def file(file: str) -> "MessageSegment":
        """
        创建一个文件消息段。

        Args:
            file (str): 文件的路径、URL 或 Base64 编码的字符串。

        Returns:
            MessageSegment: 一个类型为 'file' 的消息段对象。
        """
        return MessageSegment(type="file", data={"file": file})

    @staticmethod
    def reply(message_id: str | int) -> "MessageSegment":
        """
        创建一个回复消息段。

        Args:
            message_id (str | int): 被回复的消息 ID。

        Returns:
            MessageSegment: 一个类型为 'reply' 的消息段对象。
        """
        return MessageSegment(type="reply", data={"id": str(message_id)})

    @staticmethod
    def rps() -> "MessageSegment":
        """
        创建一个猜拳魔法表情消息段。

        Returns:
            MessageSegment: 一个类型为 'rps' 的消息段对象。
        """
        return MessageSegment(type="rps", data={})

    @staticmethod
    def dice() -> "MessageSegment":
        """
        创建一个掷骰子魔法表情消息段。

        Returns:
            MessageSegment: 一个类型为 'dice' 的消息段对象。
        """
        return MessageSegment(type="dice", data={})

    @staticmethod
    def shake() -> "MessageSegment":
        """
        创建一个戳一戳消息段。

        Returns:
            MessageSegment: 一个类型为 'shake' 的消息段对象。
        """
        return MessageSegment(type="shake", data={})

    @staticmethod
    def anonymous(ignore: bool = False) -> "MessageSegment":
        """
        创建一个匿名消息段。

        Args:
            ignore (bool, optional): 发送失败时是否忽略。Defaults to False.

        Returns:
            MessageSegment: 一个类型为 'anonymous' 的消息段对象。
        """
        return MessageSegment(type="anonymous", data={"ignore": "1" if ignore else "0"})

    @staticmethod
    def contact(contact_type: str, contact_id: int) -> "MessageSegment":
        """
        创建一个推荐好友/群消息段。

        Args:
            contact_type (str): 推荐类型，'qq' 或 'group'。
            contact_id (int): 被推荐的 QQ 号或群号。

        Returns:
            MessageSegment: 一个类型为 'contact' 的消息段对象。
        """
        return MessageSegment(type="contact", data={"type": contact_type, "id": str(contact_id)})

    @staticmethod
    def location(lat: float, lon: float, title: str = "", content: str = "") -> "MessageSegment":
        """
        创建一个位置消息段。

        Args:
            lat (float): 纬度。
            lon (float): 经度。
            title (str, optional): 标题。Defaults to "".
            content (str, optional): 内容描述。Defaults to "".

        Returns:
            MessageSegment: 一个类型为 'location' 的消息段对象。
        """
        data = {"lat": str(lat), "lon": str(lon)}
        if title:
            data["title"] = title
        if content:
            data["content"] = content
        return MessageSegment(type="location", data=data)