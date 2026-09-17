from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import discord

from extensions.punipuni import catalog
from extensions.punipuni import client as puni_client
import paypayu

logger = logging.getLogger("Punipuni.Service")

JOB_QUEUE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "punipuni" / "job_queue.json"
JOB_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

class JobStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    IN_QUEUE = "IN_QUEUE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

def build_service_embed(panel_key: str, guild_id: int) -> discord.Embed:
    cfg = catalog.ITEM_CONFIG[panel_key]
    embed = discord.Embed(
        title=cfg["title"],
        description=cfg["description"],
        color=cfg["color"]
    )
    embed.set_footer(text=f"価格: {cfg['price']}円")
    return embed


class JobQueueManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._load()

    def _load(self):
        if JOB_QUEUE_FILE.exists():
            try:
                with open(JOB_QUEUE_FILE, "r", encoding="utf-8") as f:
                    self.jobs = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.jobs = {"jobs": []}
        else:
            self.jobs = {"jobs": []}
        self._save()

    def _save(self):
        with open(JOB_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.jobs, f, indent=2, ensure_ascii=False)

    async def create_job(
        self,
        user_id: int,
        channel_id: int,
        service_type: str,
        stage_id: str,
        loop_count: int,
        price: int,
        paypay_link: str
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone(timedelta(hours=9))).isoformat()
        
        job = {
            "job_id": job_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "service_type": service_type,
            "stage_id": stage_id,
            "loop_count": loop_count,
            "price": price,
            "status": JobStatus.PENDING_PAYMENT,
            "paypay_link": paypay_link,
            "created_at": now,
            "updated_at": now,
            "error_message": None
        }
        
        async with self._lock:
            self.jobs["jobs"].append(job)
            self._save()
            
        logger.info(f"Job created: {job_id} for user {user_id}")
        return job_id

    async def update_status(self, job_id: str, status: str, error_message: Optional[str] = None):
        async with self._lock:
            for job in self.jobs["jobs"]:
                if job["job_id"] == job_id:
                    job["status"] = status
                    job["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
                    if error_message:
                        job["error_message"] = error_message
                    self._save()
                    logger.info(f"Job {job_id} status updated to {status}")
                    return True
        return False

    async def check_payment_and_advance(self, job_id: str, bot: discord.Client):
        async with self._lock:
            job = next((j for j in self.jobs["jobs"] if j["job_id"] == job_id), None)
            if not job or job["status"] != JobStatus.PENDING_PAYMENT:
                return False

        link = job["paypay_link"]
        is_paid = await paypayu.check_link(link)
        
        if is_paid:
            await self.update_status(job_id, JobStatus.PAID)
            channel = bot.get_channel(job["channel_id"])
            if channel:
                embed = discord.Embed(
                    title="✅ 支払い確認完了",
                    description="お支払いを確認しました。キューに追加し、順次実行いたします。",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)
            return True
        return False

    async def _worker_loop(self, bot: discord.Client):
        logger.info("JobQueueManager worker started.")
        while self._running:
            try:
                async with self._lock:
                    pending_jobs = [
                        j for j in self.jobs["jobs"] 
                        if j["status"] in (JobStatus.PAID, JobStatus.IN_QUEUE)
                    ]
                
                for job in pending_jobs:
                    await self.update_status(job["job_id"], JobStatus.RUNNING)
                    success, msg = await self._execute_job(job, bot)
                    
                    if success:
                        await self.update_status(job["job_id"], JobStatus.COMPLETED)
                    else:
                        await self.update_status(job["job_id"], JobStatus.FAILED, msg)
                        
                    channel = bot.get_channel(job["channel_id"])
                    if channel:
                        color = discord.Color.green() if success else discord.Color.red()
                        title = "✅ 代行完了" if success else "❌ 代行失敗"
                        embed = discord.Embed(title=title, description=msg, color=color)
                        await channel.send(embed=embed)
                        
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)
            
            await asyncio.sleep(5)

    async def _execute_job(self, job: Dict[str, Any], bot: discord.Client) -> tuple[bool, str]:
        try:
            client = puni_client.PunipuniGameClient()
            
            channel = bot.get_channel(job["channel_id"])

            if channel:
                await channel.send(f"⏳ <@{job['user_id']}> の代行を開始します... (Stage: {job['stage_id']}, Loops: {job['loop_count']})")

            for i in range(job["loop_count"]):
                await client.login(job.get("ywp_token", "mock_token"))
                await client.start_game(job["stage_id"])
                await asyncio.sleep(2)
                result = await client.end_game(job["stage_id"])
                
                if result.get("resultCode") != "S0000" and result.get("resultCode") != "OK":
                    return False, f"ステージ {job['stage_id']} の周回 {i+1}回目でエラー: {result.get('resultMessage', '不明なエラー')}"
                
                await asyncio.sleep(1)

            return True, f"{job['loop_count']}回の周回が正常に完了しました。"
            
        except Exception as e:
            logger.error(f"Job execution failed: {e}", exc_info=True)
            return False, f"実行中に予期せぬエラーが発生しました: {str(e)}"

    def start_worker(self, bot: discord.Client):
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop(bot))

    def stop_worker(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

job_queue_manager = JobQueueManager()
