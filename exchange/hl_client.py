from __future__ import annotations

import logging
import time
from typing import Any, Optional

import msgpack
import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_hex

from core.config import AppConfig
from core.exceptions import ExchangeError, OrderError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.hyperliquid.xyz"
_EXCHANGE = f"{_BASE_URL}/exchange"
_INFO = f"{_BASE_URL}/info"

# ── EIP-712 도메인 (Hyperliquid L1) ─────────────────────────────────────────
_L1_DOMAIN = {
    "chainId": 1337,
    "name": "Exchange",
    "verifyingContract": "0x0000000000000000000000000000000000000000",
    "version": "1",
}
_AGENT_TYPES = {
    "Agent": [
        {"name": "source", "type": "string"},
        {"name": "connectionId", "type": "bytes32"},
    ],
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
}


def _float_to_wire(x: float) -> str:
    from decimal import Decimal
    rounded = f"{x:.8f}"
    if rounded == "-0":
        rounded = "0"
    return f"{Decimal(rounded).normalize():f}"


def _address_to_bytes(addr: str) -> bytes:
    return bytes.fromhex(addr[2:] if addr.startswith("0x") else addr)


def _action_hash(action: Any, vault_address: Optional[str], nonce: int) -> bytes:
    data = msgpack.packb(action, use_bin_type=True)
    data += nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01"
        data += _address_to_bytes(vault_address)
    return keccak(data)


def _sign_l1_action(account: Account, action: Any, vault_address: Optional[str], nonce: int) -> dict:
    h = _action_hash(action, vault_address, nonce)
    phantom = {"source": "a", "connectionId": h}
    payload = {
        "domain": _L1_DOMAIN,
        "types": _AGENT_TYPES,
        "primaryType": "Agent",
        "message": phantom,
    }
    structured = encode_typed_data(full_message=payload)
    signed = account.sign_message(structured)
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


class HlClient:
    """Hyperliquid Perpetual REST 클라이언트"""

    def __init__(self, config: AppConfig) -> None:
        self._user = config.user_address.lower()
        self._account = Account.from_key(config.signer_private_key)
        self._signer = self._account.address.lower()
        self._dry_run = config.mode.dry_run
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        # 심볼 → asset 인덱스 캐시
        self._asset_index: dict[str, int] = {}

    # ── 심볼→인덱스 ─────────────────────────────────────────────────────────

    def _get_asset_index(self, coin: str) -> int:
        """BTC, ETH 등 심볼을 Hyperliquid asset index로 변환"""
        if not self._asset_index:
            meta = self._info({"type": "meta"})
            for i, asset in enumerate(meta.get("universe", [])):
                self._asset_index[asset["name"]] = i
        # symbol 형식이 "BTCUSDT"면 "BTC"만 추출
        coin_clean = coin.replace("USDT", "").replace("PERP", "").replace("-PERP", "")
        if coin_clean not in self._asset_index:
            raise ExchangeError(f"알 수 없는 심볼: {coin} (clean={coin_clean})")
        return self._asset_index[coin_clean]

    # ── 저수준 HTTP ─────────────────────────────────────────────────────────

    def _info(self, payload: dict) -> Any:
        resp = self._session.post(_INFO, json=payload, timeout=10)
        return self._parse(resp)

    def _exchange(self, action: dict) -> Any:
        nonce = int(time.time() * 1000)
        sig = _sign_l1_action(self._account, action, None, nonce)
        body = {
            "action": action,
            "nonce": nonce,
            "signature": sig,
        }
        resp = self._session.post(_EXCHANGE, json=body, timeout=10)
        return self._parse(resp)

    @staticmethod
    def _parse(resp: requests.Response) -> Any:
        try:
            data = resp.json()
        except Exception as e:
            raise ExchangeError(f"JSON 파싱 실패: {resp.text}") from e
        if resp.status_code >= 400:
            raise ExchangeError(f"API 에러 {resp.status_code}: {data}")
        # Hyperliquid 에러 응답: {"status": "err", "response": "..."}
        if isinstance(data, dict) and data.get("status") == "err":
            raise ExchangeError(f"HL 에러: {data.get('response')}")
        return data

    # ── 공개 API ────────────────────────────────────────────────────────────

    def get_exchange_info(self) -> dict:
        return self._info({"type": "meta"})

    def get_ticker_price(self, symbol: str) -> float:
        coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "")
        mids = self._info({"type": "allMids"})
        if coin not in mids:
            raise ExchangeError(f"가격 없음: {symbol}")
        return float(mids[coin])

    def get_funding_rate(self, symbol: str) -> float:
        coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "")
        data = self._info({"type": "metaAndAssetCtxs"})
        universe = data[0].get("universe", [])
        ctxs = data[1]
        for i, asset in enumerate(universe):
            if asset["name"] == coin:
                return float(ctxs[i].get("funding", 0))
        return 0.0

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> list:
        coin = symbol.replace("USDT", "").replace("PERP", "").replace("-PERP", "")
        now_ms = int(time.time() * 1000)
        # interval 문자열 → ms 변환
        _interval_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                        "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
        step = _interval_ms.get(interval, 3_600_000)
        start_ms = now_ms - step * limit
        return self._info({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval,
                    "startTime": start_ms, "endTime": now_ms},
        })

    # ── 인증 API ────────────────────────────────────────────────────────────

    def validate_api_permissions(self) -> None:
        """Hyperliquid는 출금이 별도 서명 필요 — 기본 확인만"""
        try:
            self.get_balance()
            logger.info("Hyperliquid 연결 확인 완료 (user=%s)", self._user)
        except Exception as e:
            raise ExchangeError(f"Hyperliquid 연결 실패: {e}") from e

    def get_account(self) -> dict:
        return self._info({"type": "clearinghouseState", "user": self._user})

    def get_balance(self) -> float:
        """
        Unified Account 호환: Perp 계좌가치 + Spot USDC를 모두 합산해서 반환.
        - 일반 계정: Perp accountValue 만 0이 아님
        - Unified 계정: Spot USDC가 perp 거래의 담보로 직접 사용됨
        """
        perp = self._info({"type": "clearinghouseState", "user": self._user})
        perp_val = float(perp.get("marginSummary", {}).get("accountValue", 0))

        try:
            spot = self._info({"type": "spotClearinghouseState", "user": self._user})
            usdc = next(
                (b for b in spot.get("balances", []) if b.get("coin") == "USDC"),
                None,
            )
            spot_val = float(usdc["total"]) if usdc else 0.0
        except Exception as e:
            logger.warning("Spot 잔고 조회 실패, Perp만 사용: %s", e)
            spot_val = 0.0

        return perp_val + spot_val

    def get_positions(self) -> list[dict]:
        data = self._info({"type": "clearinghouseState", "user": self._user})
        positions = []
        for pos in data.get("assetPositions", []):
            p = pos.get("position", {})
            size = float(p.get("szi", 0))
            if size != 0:
                positions.append({
                    "symbol": p.get("coin", "") + "USDT",
                    "positionAmt": size,
                    "entryPrice": p.get("entryPx"),
                    "unrealizedProfit": p.get("unrealizedPnl"),
                    "leverage": p.get("leverage", {}).get("value"),
                })
        return positions

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        data = self._info({"type": "openOrders", "user": self._user})
        if symbol:
            coin = symbol.replace("USDT", "")
            data = [o for o in data if o.get("coin") == coin]
        return data

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] set_leverage %s x%d", symbol, leverage)
            return {}
        asset = self._get_asset_index(symbol)
        return self._exchange({
            "type": "updateLeverage",
            "asset": asset,
            "isCross": False,   # ISOLATED
            "leverage": leverage,
        })

    def set_margin_type(self, symbol: str, margin_type: str) -> dict:
        # Hyperliquid: set_leverage 에서 isCross로 제어
        if self._dry_run:
            logger.info("[DRY_RUN] set_margin_type %s %s", symbol, margin_type)
        return {}

    # ── 주문 ────────────────────────────────────────────────────────────────

    def market_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] MARKET %s %s qty=%s", side, symbol, quantity)
            return {"orderId": f"DRY_{int(time.time()*1000)}", "status": "FILLED"}
        asset = self._get_asset_index(symbol)
        is_buy = side.upper() in ("BUY", "LONG")
        price = self.get_ticker_price(symbol)
        # 시장가 = 슬리피지 허용 지정가 (tif=Ioc)
        slippage = 0.05
        limit_px = price * (1 + slippage) if is_buy else price * (1 - slippage)
        order_wire = {
            "a": asset,
            "b": is_buy,
            "p": _float_to_wire(limit_px),
            "s": _float_to_wire(quantity),
            "r": reduce_only,
            "t": {"limit": {"tif": "Ioc"}},
        }
        data = self._exchange({
            "type": "order",
            "orders": [order_wire],
            "grouping": "na",
        })
        statuses = data.get("response", {}).get("data", {}).get("statuses", [{}])
        filled = statuses[0].get("filled", {})
        return {
            "orderId": str(filled.get("oid", "")),
            "status": "FILLED",
            "avgPrice": filled.get("avgPx"),
        }

    def stop_market_order(
        self, symbol: str, side: str, stop_price: float, quantity: float,
        close_position: bool = False,
    ) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] STOP_MARKET %s %s stopPrice=%s", side, symbol, stop_price)
            return {"orderId": f"DRY_SL_{int(time.time()*1000)}", "status": "NEW"}
        asset = self._get_asset_index(symbol)
        is_buy = side.upper() in ("BUY", "LONG")
        order_wire = {
            "a": asset,
            "b": is_buy,
            "p": _float_to_wire(stop_price),
            "s": _float_to_wire(quantity),
            "r": True,  # SL은 항상 reduce-only
            "t": {"trigger": {
                "isMarket": True,
                "triggerPx": _float_to_wire(stop_price),
                "tpsl": "sl",
            }},
        }
        data = self._exchange({
            "type": "order",
            "orders": [order_wire],
            "grouping": "na",
        })
        statuses = data.get("response", {}).get("data", {}).get("statuses", [{}])
        oid = statuses[0].get("resting", {}).get("oid", "")
        return {"orderId": str(oid), "status": "NEW"}

    def take_profit_order(
        self, symbol: str, side: str, stop_price: float, quantity: float
    ) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] TAKE_PROFIT %s %s stopPrice=%s", side, symbol, stop_price)
            return {"orderId": f"DRY_TP_{int(time.time()*1000)}", "status": "NEW"}
        asset = self._get_asset_index(symbol)
        is_buy = side.upper() in ("BUY", "LONG")
        order_wire = {
            "a": asset,
            "b": is_buy,
            "p": _float_to_wire(stop_price),
            "s": _float_to_wire(quantity),
            "r": True,
            "t": {"trigger": {
                "isMarket": True,
                "triggerPx": _float_to_wire(stop_price),
                "tpsl": "tp",
            }},
        }
        data = self._exchange({
            "type": "order",
            "orders": [order_wire],
            "grouping": "na",
        })
        statuses = data.get("response", {}).get("data", {}).get("statuses", [{}])
        oid = statuses[0].get("resting", {}).get("oid", "")
        return {"orderId": str(oid), "status": "NEW"}

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_order %s %s", symbol, order_id)
            return {}
        asset = self._get_asset_index(symbol)
        try:
            return self._exchange({
                "type": "cancel",
                "cancels": [{"a": asset, "o": int(order_id)}],
            })
        except ExchangeError as e:
            if "Unknown order" in str(e):
                return {}
            raise

    def cancel_all_orders(self, symbol: str) -> dict:
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_all_orders %s", symbol)
            return {}
        orders = self.get_open_orders(symbol)
        if not orders:
            return {}
        asset = self._get_asset_index(symbol)
        cancels = [{"a": asset, "o": int(o["oid"])} for o in orders]
        return self._exchange({"type": "cancel", "cancels": cancels})

    def close_position(self, symbol: str, side: str, quantity: float) -> dict:
        close_side = "SELL" if side == "LONG" else "BUY"
        return self.market_order(symbol, close_side, quantity, reduce_only=True)
