from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import string
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Punipuni.L5Account")

POOL_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "punipuni" / "l5_pool.json"
POOL_FILE.parent.mkdir(parents=True, exist_ok=True)

# 環境変数での制御
POOL_AUTO_ENABLED = os.getenv("PUNIPUNI_POOL_AUTO", "1") == "1"
POOL_TARGET = int(os.getenv("PUNIPUNI_POOL_TARGET", "100"))


def _load_pool() -> list[dict]:
    if POOL_FILE.exists():
        try:
            with open(POOL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _save_pool(pool: list[dict]) -> None:
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=2, ensure_ascii=False)


def get_pool_status() -> dict:
    pool = _load_pool()
    available = [a for a in pool if a.get("status") == "available"]
    return {
        "total": len(pool),
        "available": len(available),
        "target": POOL_TARGET,
        "auto_enabled": POOL_AUTO_ENABLED,
    }


async def generate_l5_id() -> Optional[dict]:
    """
    L5 IDを新規生成する。
    実際の実装では mail.tm API でメールを取得し、
    Selenium + geckodriver で Level5 の登録ページを操作する。
    ここでは既存の level5-gen/main.py のロジックを呼び出す想定。
    """
    # TODO: 実際の生成ロジックは level5-gen/main.py から移植が必要
    # 現在はプレースホルダーとしてNoneを返す
    logger.warning("L5 ID generation not yet implemented in new structure")
    return None


async def refill_pool_if_needed() -> int:
    """ストックが目標未満なら自動補充する"""
    if not POOL_AUTO_ENABLED:
        return 0

    status = get_pool_status()
    deficit = status["target"] - status["available"]
    if deficit <= 0:
        return 0

    generated = 0
    for _ in range(min(deficit, 5)):  # 一度に最大5個まで
        account = await generate_l5_id()
        if account:
            pool = _load_pool()
            pool.append(account)
            _save_pool(pool)
            generated += 1
            await asyncio.sleep(2)  # レート制限対策

    if generated > 0:
        logger.info(f"L5 pool refilled: {generated} accounts added")
    return generated


def consume_account() -> Optional[dict]:
    """利用可能なアカウントを1つ消費する"""
    pool = _load_pool()
    for account in pool:
        if account.get("status") == "available":
            account["status"] = "consumed"
            account["consumed_at"] = time.time()
            _save_pool(pool)
            return account
    return None
