"""exchange/hl_client.py — Hyperliquid EIP-712 서명 생성 검증, 모킹된 응답 처리"""
import time
from unittest.mock import MagicMock, patch

import pytest
import responses as resp_mock

from core.exceptions import ExchangeError
from exchange.hl_client import HlClient, _float_to_wire, _action_hash, _sign_l1_action

# 테스트용 더미 이더리움 키쌍 (공개 정보, 실서버 사용 불가)
_TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_TEST_SIGNER_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
_TEST_USER_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def _make_config(dry_run: bool = True):
    cfg = MagicMock()
    cfg.user_address = _TEST_USER_ADDR
    cfg.signer_address = _TEST_SIGNER_ADDR
    cfg.signer_private_key = _TEST_PRIVATE_KEY
    cfg.mode.dry_run = dry_run
    return cfg


class TestSigning:
    def test_float_to_wire_basic(self):
        assert _float_to_wire(50000.0) == "50000"
        assert _float_to_wire(0.001) == "0.001"
        assert _float_to_wire(49000.12345678) == "49000.12345678"

    def test_action_hash_returns_bytes32(self):
        h = _action_hash({"type": "order"}, None, 1234567890000)
        assert isinstance(h, bytes)
        assert len(h) == 32

    def test_action_hash_deterministic(self):
        action = {"type": "order", "orders": []}
        h1 = _action_hash(action, None, 999)
        h2 = _action_hash(action, None, 999)
        assert h1 == h2

    def test_action_hash_differs_by_nonce(self):
        action = {"type": "order"}
        h1 = _action_hash(action, None, 1000)
        h2 = _action_hash(action, None, 1001)
        assert h1 != h2

    def test_sign_l1_action_returns_r_s_v(self):
        from eth_account import Account
        wallet = Account.from_key(_TEST_PRIVATE_KEY)
        sig = _sign_l1_action(wallet, {"type": "order", "orders": []}, None, 1234567890000)
        assert "r" in sig and "s" in sig and "v" in sig
        assert sig["r"].startswith("0x")
        assert sig["v"] in (27, 28)


class TestParseResponse:
    def test_parse_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "response": {"data": {}}}
        result = HlClient._parse(mock_resp)
        assert result["status"] == "ok"

    def test_parse_http_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "bad request"}
        with pytest.raises(ExchangeError):
            HlClient._parse(mock_resp)

    def test_parse_hl_error_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "err", "response": "Invalid order"}
        with pytest.raises(ExchangeError):
            HlClient._parse(mock_resp)


class TestDryRunOrders:
    def setup_method(self):
        self.client = HlClient(_make_config(dry_run=True))

    def test_market_order_dry_run(self):
        result = self.client.market_order("BTCUSDT", "BUY", 0.001)
        assert "DRY_" in result["orderId"]
        assert result["status"] == "FILLED"

    def test_stop_market_dry_run(self):
        result = self.client.stop_market_order("BTCUSDT", "SELL", 49000.0, 0.001)
        assert "DRY_SL_" in result["orderId"]

    def test_take_profit_dry_run(self):
        result = self.client.take_profit_order("BTCUSDT", "SELL", 52000.0, 0.001)
        assert "DRY_TP_" in result["orderId"]

    def test_set_leverage_dry_run(self):
        result = self.client.set_leverage("BTCUSDT", 5)
        assert result == {}

    def test_cancel_order_dry_run(self):
        result = self.client.cancel_order("BTCUSDT", "12345")
        assert result == {}


@resp_mock.activate
class TestGetTickerPrice:
    def test_success(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.hyperliquid.xyz/info",
            json={"BTC": "50000.00"},
            status=200,
        )
        client = HlClient(_make_config())
        price = client.get_ticker_price("BTCUSDT")
        assert price == pytest.approx(50000.0)

    def test_missing_symbol_raises(self):
        resp_mock.add(
            resp_mock.POST,
            "https://api.hyperliquid.xyz/info",
            json={"BTC": "50000.00"},
            status=200,
        )
        client = HlClient(_make_config())
        with pytest.raises(ExchangeError):
            client.get_ticker_price("XYZUSDT")
