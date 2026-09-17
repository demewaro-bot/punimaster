from __future__ import annotations

import discord

# 代行サービスの設定
ITEM_CONFIG = {
    "auto_loop": {
        "title": "自動周回代行",
        "description": "指定したステージを自動で周回します。\n経験値稼ぎや素材集めにご利用ください。",
        "price": 10,  # 1周あたりの単価（円）
        "color": discord.Color.blue(),
    },
    "account_create": {
        "title": "アカウント作成代行",
        "description": "L5 ID付きの新しいゲームアカウントを作成します。\nリセマラやサブアカウント用にどうぞ。",
        "price": 200,  # 1アカウントあたりの単価（円）
        "color": discord.Color.green(),
    },
}

def item_keys() -> list[str]:
    return list(ITEM_CONFIG.keys())
