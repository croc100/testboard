#!/usr/bin/env python3
"""
Hyperliquid Spot → Perp 일회성 이체 스크립트.

사용법:
    .venv/bin/python scripts/transfer_to_perp.py [금액_USDC]
    예) .venv/bin/python scripts/transfer_to_perp.py 6
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_hex

from core.config import load_config

load_dotenv()


_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "HyperliquidTransaction:UsdClassTransfer": [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "toPerp", "type": "bool"},
        {"name": "nonce", "type": "uint64"},
    ],
}


def main() -> None:
    amount = sys.argv[1] if len(sys.argv) > 1 else "6"

    cfg = load_config()
    account = Account.from_key(cfg.signer_private_key)
    print(f"지갑: {account.address}")
    print(f"이체 금액: {amount} USDC")
    print(f"방향: Spot → Perp")

    nonce = int(time.time() * 1000)
    action = {
        "type": "usdClassTransfer",
        "amount": str(amount),
        "toPerp": True,
        "nonce": nonce,
        "signatureChainId": "0x66eee",
        "hyperliquidChain": "Mainnet",
    }

    # User-signed action
    payload = {
        "domain": {
            "name": "HyperliquidSignTransaction",
            "version": "1",
            "chainId": int("0x66eee", 16),
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "types": _TYPES,
        "primaryType": "HyperliquidTransaction:UsdClassTransfer",
        "message": action,
    }

    msg = encode_typed_data(full_message=payload)
    signed = account.sign_message(msg)
    sig = {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}

    body = {"action": action, "nonce": nonce, "signature": sig}
    print("\n→ Hyperliquid에 요청 중...")
    resp = requests.post("https://api.hyperliquid.xyz/exchange",
                         json=body, timeout=10)
    print(f"HTTP {resp.status_code}")
    print(resp.json())


if __name__ == "__main__":
    main()
