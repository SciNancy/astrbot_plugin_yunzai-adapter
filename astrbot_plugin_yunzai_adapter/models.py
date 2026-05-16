from typing import Any, Dict, List, Literal, Optional

from msgspec import Struct


class Message(Struct):
    """单条消息元素"""
    type: Optional[str] = None
    data: Optional[Any] = None


class MessageReceive(Struct):
    """AstrBot → Yunzai 的消息格式"""
    type: str = 'message'
    bot_self_id: str = ''
    message_type: Literal['group', 'private'] = 'private'
    user_id: str = ''
    group_id: Optional[str] = None
    sender: Dict[str, Any] = {}
    message: List[Message] = []
    msg_id: str = ''


class MessageSend(Struct):
    """Yunzai → AstrBot 的回复格式"""
    type: str = 'reply'
    target_type: Literal['group', 'private'] = 'private'
    target_id: Optional[str] = None
    user_id: Optional[str] = None
    group_id: Optional[str] = None
    msg_id: Optional[str] = None
    bot_self_id: Optional[str] = None
    content: Optional[List[Message]] = None
    quote: bool = False
    time: int = 0
