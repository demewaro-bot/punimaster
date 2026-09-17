"""ぷにぷに 自動代行 — Discord Bot"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOKEN_FILE = ROOT / "token.json"
logger = logging.getLogger("Punipuni")


def load_token() -> str:
    if not TOKEN_FILE.is_file():
        raise SystemExit(
            f"token.json がありません。\n"
            f"  {TOKEN_FILE}\n"
            f"  token.json.example をコピーして Bot トークンを設定してください。"
        )
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    token = str(data.get("token") or "").strip()
    if not token or token.startswith("ここに"):
        raise SystemExit("token.json の token に Discord Bot トークンを設定してください。")
    return token


class PunipuniBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # ぷにぷに代行Cogの読み込み
        await self.load_extension("extensions.Punipuni")
        
        # PayPayログインCogの読み込み
        await self.load_extension("paypay_login")
        
        # ジョブキューワーカーの起動
        from extensions.punipuni.service import job_queue_manager
        job_queue_manager.start_worker(self)
        logger.info("JobQueueManager worker started.")

        # スラッシュコマンドの同期
        guild_id = (os.getenv("PUNIPUNI_GUILD_ID") or "").strip()
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("slash sync (guild %s): %d", guild_id, len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("slash sync (global): %d", len(synced))

    async def on_ready(self) -> None:
        logger.info("logged in as %s (%s)", self.user, self.user and self.user.id)
        
        # 起動時に未支払いのジョブがあれば支払い確認を再開するタスクを立てる（必要に応じて）
        from extensions.punipuni.service import job_queue_manager
        self.loop.create_task(self._check_pending_payments(job_queue_manager))

    async def _check_pending_payments(self, manager):
        from extensions.punipuni.service import JobStatus
        while True:
            try:
                async with manager._lock:
                    pending_jobs = [j for j in manager.jobs["jobs"] if j["status"] == JobStatus.PENDING_PAYMENT]
                for job in pending_jobs:
                    await manager.check_payment_and_advance(job["job_id"], self)
            except Exception as e:
                logger.error(f"Pending payment check error: {e}", exc_info=True)
            await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(seconds=30))


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = PunipuniBot()
    bot.run(load_token(), root_logger=True)


if __name__ == "__main__":
    main()
