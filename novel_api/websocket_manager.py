"""
websocket_manager.py - WebSocket 连接管理

管理 WebSocket 连接，提供广播消息能力。
"""

from __future__ import annotations

import json
import asyncio
from typing import Set, Dict, Any
from fastapi import WebSocket


class WebSocketManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """接受并添加新的 WebSocket 连接"""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        """移除断开连接的 WebSocket"""
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """向所有连接的客户端广播消息"""
        async with self._lock:
            disconnected = set()
            for ws in self._connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    disconnected.add(ws)
            # 清理断开连接
            for ws in disconnected:
                self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
