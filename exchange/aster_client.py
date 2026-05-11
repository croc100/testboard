from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

from core.config import AppConfig
from core.exceptions import ExchangeError, OrderError

logger = logging.getLogger(__name__)

# ── EIP-712 도메인 (AsterDEX V3 고정값) ──────────────────────────────────────
_EIP712_DOMAIN = {
    "name": "AsterSignTransaction",
    "version": "1",
    "chainId": 1666,
    "verifyingContract": "0x0000000000000000000000000000000000000000",
}

_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Message": [{"name": "msg", "type": "string"}],
}

_WITHDRAW_PERMISSION = "enabling_withdrawal"


class AsterClient:
    """AsterDEX Perpetual REST 클라이언트 (V3 EIP-712 서명)"""

    def __init__(self, config: AppConfig) -> None:
        self._api_url = config.exchange.api_url.rstrip("/")
        self._user_address = config.user_address        # 메인 지갑 주소
        self._signer_address = config.signer_address    # API 서브 지갑 주소
        self._private_key = config.signer_private_key   # API 서브 지갑 개인 키
        self._dry_run = config.mode.dry_run
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/x-www-form-urlencoded"})

    # ── EIP-712 서명 ─────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> tuple[str, str]:
        """
        params에 nonce·signer·user를 추가하고 EIP-712 서명을 반환한다.
        Returns (query_string, signature_hex)
        """
        p = dict(params)  # 원본 변경 방지
        p["nonce"] = str(math.trunc(time.time() * 1_000_000))
        p["signer"] = self._signer_address
        p["user"] = self._user_address

        param_str = urlencode(p)
        typed_data = {
            "types": _EIP712_TYPES,
            "primaryType": "Message",
            "domain": _EIP712_DOMAIN,
            "message": {"msg": param_str},
        }
        message = encode_typed_data(full_message=typed_data)
        signed = Account.sign_message(message, private_key=self._private_key)
        return param_str, signed.signature.hex()

    # ── 저수준 HTTP ─────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        if signed:
            param_str, sig = self._sign(params or {})
            url = f"{self._api_url}{path}?{param_str}&signature={sig}"
            resp = self._session.get(url, timeout=10)
        else:
            resp = self._session.get(
                f"{self._api_url}{path}", params=params or {}, timeout=10
            )
        return self._parse(resp)

    def _post(self, path: str, params: dict | None = None) -> Any:
        param_str, sig = self._sign(params or {})
        url = f"{self._api_url}{path}?{param_str}&signature={sig}"
        resp = self._session.post(url, timeout=10)
        return self._parse(resp)

    def _delete(self, path: str, params: dict | None = None) -> Any:
        param_str, sig = self._sign(params or {})
        url = f"{self._api_url}{path}?{param_str}&signature={sig}"
        resp = self._session.delete(url, timeout=10)
        return self._parse(resp)

    @staticmethod
    def _parse(resp: requests.Response) -> Any:
        try:
            data = resp.json()
        except Exception as e:
            raise ExchangeError(f"JSON 파싱 실패: {resp.text}") from e
        if resp.status_code >= 400:
            raise ExchangeError(f"API 에러 {resp.status_code}: {data}")
        return data

    # ── 공개 API ────────────────────────────────────────────────────────────

    def get_exchange_info(self) -> dict:
        return self._get("/fapi/v1/exchangeInfo")

    def get_ticker_price(self, symbol: str) -> float:
        data = self._get("/fapi/v1/ticker/price", {"symbol": symbol})
        return float(data["price"])

    def get_funding_rate(self, symbol: str) -> float:
        data = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(data.get("lastFundingRate", 0))

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list:
        return self._get("/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })

    # ── 인증 API ────────────────────────────────────────────────────────────

    def validate_api_permissions(self) -> None:
        """Withdraw 권한 감지 시 즉시 에러"""
        data = self._get("/fapi/v1/account", signed=True)
        can_trade = data.get("canTrade", False)
        if not can_trade:
            raise ExchangeError("API 키에 Trade 권한이 없습니다.")
        # AsterDEX / 바이낸스 계정 권한 필드 체크
        if data.get("canWithdraw") or data.get(_WITHDRAW_PERMISSION):
            raise ExchangeError(
                "API 키에 Withdraw 권한이 감지되었습니다. "
                "Trade only 키를 사용하세요. 절대 원칙 #1 위반."
            )
        logger.info("API 권한 검증 통과 (Trade only)")

    def get_account(self) -> dict:
        return self._get("/fapi/v2/account", signed=True)

    def get_balance(self) -> float:
        data = self._get("/fapi/v2/balance", signed=True)
        for asset in data:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))
        return 0.0

    def get_positions(self) -> list[dict]:
        data = self._get("/fapi/v2/positionRisk", signed=True)
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        return self._get("/fapi/v1/openOrders", params, signed=True)

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] set_leverage %s x%d", symbol, leverage)
            return {}
        return self._post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    def set_margin_type(self, symbol: str, margin_type: str) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] set_margin_type %s %s", symbol, margin_type)
            return {}
        try:
            return self._post("/fapi/v1/marginType", {
                "symbol": symbol, "marginType": margin_type,
            })
        except ExchangeError as e:
            # 이미 해당 타입이면 -4046 에러 — 무시
            if "-4046" in str(e):
                return {}
            raise

    # ── 주문 ────────────────────────────────────────────────────────────────

    def market_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> dict:
        params: dict = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if self._dry_run:
            logger.info("[DRY_RUN] MARKET %s %s qty=%s reduceOnly=%s",
                        side, symbol, quantity, reduce_only)
            return {"orderId": f"DRY_{int(time.time()*1000)}", "status": "FILLED"}
        return self._post("/fapi/v1/order", params)

    def stop_market_order(
        self, symbol: str, side: str, stop_price: float, quantity: float,
        close_position: bool = False,
    ) -> dict:
        params: dict = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": f"{stop_price:.4f}",
            "closePosition": "true" if close_position else "false",
        }
        if not close_position:
            params["quantity"] = quantity
        if self._dry_run:
            logger.info("[DRY_RUN] STOP_MARKET %s %s stopPrice=%s",
                        side, symbol, stop_price)
            return {"orderId": f"DRY_SL_{int(time.time()*1000)}", "status": "NEW"}
        return self._post("/fapi/v1/order", params)

    def take_profit_order(
        self, symbol: str, side: str, stop_price: float, quantity: float
    ) -> dict:
        params: dict = {
            "symbol": symbol,
            "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": f"{stop_price:.4f}",
            "quantity": quantity,
        }
        if self._dry_run:
            logger.info("[DRY_RUN] TAKE_PROFIT %s %s stopPrice=%s",
                        side, symbol, stop_price)
            return {"orderId": f"DRY_TP_{int(time.time()*1000)}", "status": "NEW"}
        return self._post("/fapi/v1/order", params)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_order %s %s", symbol, order_id)
            return {}
        try:
            return self._delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
        except ExchangeError as e:
            if "-2011" in str(e):  # Unknown order
                return {}
            raise

    def cancel_all_orders(self, symbol: str) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_all_orders %s", symbol)
            return {}
        return self._delete("/fapi/v1/allOpenOrders", {"symbol": symbol})

    def close_position(self, symbol: str, side: str, quantity: float) -> dict:
        close_side = "SELL" if side == "LONG" else "BUY"
        return self.market_order(symbol, close_side, quantity, reduce_only=True)
