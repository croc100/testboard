"""Phase 2 — WebSocket 클라이언트 (현재 미구현, 플레이스홀더)"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AsterWebSocket:
    """REST 폴링 대체용 WebSocket 스트림 (Phase 2)"""

    def __init__(self, api_url: str, api_key: str, api_secret: str) -> None:
        self._ws_url = api_url.replace("https://", "wss://").replace("http://", "ws://")
        self._api_key = api_key
        self._api_secret = api_secret
        logger.warning("AsterWebSocket is not yet implemented (Phase 2).")

    def start(self) -> None:
        raise NotImplementedError("WebSocket 클라이언트는 Phase 2에서 구현됩니다.")
