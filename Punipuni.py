"""ぷにぷに 自動代行 Discord Cog"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands, ui
from discord.ext import commands

from extensions.punipuni import service as punisvc
from extensions.punipuni import catalog
from extensions.punipuni.catalog import ITEM_CONFIG, item_keys

logger = logging.getLogger("Punipuni.Cog")


def _guild_id(ctx) -> int:
    if ctx.guild is not None:
        return ctx.guild.id
    if ctx.interaction is not None and ctx.interaction.guild_id:
        return ctx.interaction.guild_id
    return 0


class PanelSetupModal(ui.Modal, title="代行パネル設置"):
    def __init__(self, panel_key: str):
        super().__init__(timeout=300)
        self.panel_key = panel_key
        cfg = ITEM_CONFIG[panel_key]
        self.p_note = ui.TextInput(
            label="追加メモ（任意・フッターに追記）",
            required=False,
            max_length=200,
        )
        self.add_item(self.p_note)

    async def on_submit(self, interaction: discord.Interaction):
        gid = interaction.guild_id or 0
        embed = punisvc.build_service_embed(self.panel_key, gid)
        if self.p_note.value and self.p_note.value.strip():
            old = embed.footer.text or ""
            embed.set_footer(text=(old + " " + self.p_note.value.strip()).strip())
        view = ServicePanelView(self.panel_key, gid)
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await interaction.response.send_message("テキストチャンネルで実行してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("パネルを設置しました。", ephemeral=True)


class ServicePanelView(ui.View):
    def __init__(self, panel_key: str, guild_id: int):
        super().__init__(timeout=None)
        self.panel_key = panel_key
        self.guild_id = guild_id

    @ui.button(label="自動周回を依頼する", style=discord.ButtonStyle.primary, custom_id="punipuni_auto_loop_request")
    async def request_auto_loop(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        cfg = catalog.ITEM_CONFIG["auto_loop"]
        price = cfg["price"]
        stage_id = "1-1" # デフォルトステージ
        loop_count = 10  # デフォルト周回数
        
        # PayPayリンクの生成（paypayuを使用）
        import paypayu
        from paypay_login import get_paypay_entry
        
        entry = get_paypay_entry(interaction.guild_id)
        if not entry:
            await interaction.followup.send("❌ このサーバーではPayPayアカウントが登録されていません。管理者に `/paypayログイン` を実行してもらってください。", ephemeral=True)
            return

        access_token = entry.get("access_token")
        uuid = entry.get("uuid")
        
        link_result = await paypayu.create_link(access_token, uuid, amount=price * loop_count)
        if link_result.get("header", {}).get("resultCode") != "S0000":
            msg = link_result.get("header", {}).get("resultMessage", "PayPayリンクの生成に失敗しました。")
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return
            
        paypay_link = link_result.get("payload", {}).get("permalink") or link_result.get("payload", {}).get("link")
        if not paypay_link:
            await interaction.followup.send("❌ PayPayリンクのURL取得に失敗しました。", ephemeral=True)
            return

        # ジョブキューに登録
        job_id = await punisvc.job_queue_manager.create_job(
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            service_type="auto_loop",
            stage_id=stage_id,
            loop_count=loop_count,
            price=price * loop_count,
            paypay_link=paypay_link
        )
        
        embed = discord.Embed(
            title="📝 代行注文を受け付けました",
            description=f"以下のPayPayリンクよりお支払いを完了させてください。\n支払い確認後、自動的にキューに入り実行されます。",
            color=discord.Color.blue()
        )
        embed.add_field(name="ジョブID", value=job_id[:8], inline=True)
        embed.add_field(name="ステージID", value=stage_id, inline=True)
        embed.add_field(name="周回数", value=str(loop_count), inline=True)
        embed.add_field(name="合計金額", value=f"{price * loop_count}円", inline=True)
        embed.add_field(name="支払いリンク", value=paypay_link, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="ステージID確認", style=discord.ButtonStyle.secondary, custom_id="punipuni_stage_id_check")
    async def check_stage_id(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("現在のデフォルトステージは `1-1` です。カスタムステージは開発中です。", ephemeral=True)


class PunipuniCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ぷにぷに", description="ぷにぷに自動代行パネルを操作します")
    @app_commands.describe(action="実行するアクション")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="パネル設置", value="panel"),
            app_commands.Choice(name="ストック確認", value="stock"),
            app_commands.Choice(name="設定変更", value="config"),
        ]
    )
    async def punipuni(self, interaction: discord.Interaction, action: str):
        if action == "panel":
            # 自動周回パネルの設置モーダルを表示
            modal = PanelSetupModal("auto_loop")
            await interaction.response.send_modal(modal)
            
        elif action == "stock":
            from extensions.punipuni.l5_account import get_pool_status
            status = get_pool_status()
            embed = discord.Embed(title="L5 ID ストック状況", description=f"現在 {status['available']} 個のL5 IDが利用可能です。", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        elif action == "config":
            await interaction.response.send_message("設定変更機能は開発中です。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PunipuniCog(bot))
