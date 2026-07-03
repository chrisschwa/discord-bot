"""
Channels cog - Auto voice channel creation and management.
"""
import logging
import discord
from discord import (
    app_commands, Embed, Colour, Interaction, Member, VoiceState,
    VoiceChannel, CategoryChannel, Permissions, PermissionOverwrite
)
from discord.ext import commands, tasks

logger = logging.getLogger("bot.cogs.channels")


class AutoVoice(commands.Cog):
    """Automatic voice channel creation and cleanup."""

    def __init__(self, bot):
        self.bot = bot
        self._triggers = {"create-new", "➕ create new channel", "create new", "💬 create voice channel", "💬-create voice channel"}

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: Member, before: VoiceState, after: VoiceState
    ):
        if not after.channel:
            return
        guild = after.channel.guild
        channel_name = after.channel.name.lower()
        if channel_name not in self._triggers:
            return
        settings = await self.bot.db.get_server_settings(guild.id)
        if not settings or not settings.get("voice_auto_enabled", False):
            return
        existing_auto = [
            ch for ch in guild.voice_channels
            if ch.name.endswith(settings.get("voice_auto_suffix", "'s-room"))
        ]
        limit = settings.get("voice_auto_limit", 10)
        if len(existing_auto) >= limit:
            return
        category_id = settings.get("voice_auto_category_id")
        category = guild.get_channel(category_id) if category_id else after.channel.category
        suffix = settings.get("voice_auto_suffix", "s-channel")
        # Use guild nickname if set, otherwise global display name
        display_name = member.nick or member.global_name or member.name
        new_name = f"{display_name}{suffix}"
        existing_ch = next((c for c in guild.voice_channels if c.name == new_name), None)
        if existing_ch:
            await member.move_to(existing_ch, reason="Auto-voice: channel already exists")
            return
        overwrites = {
            guild.default_role: PermissionOverwrite(read_messages=False, connect=False, speak=False, view_channel=False),
            member: PermissionOverwrite(read_messages=True, connect=True, speak=True, manage_channels=True, view_channel=True),
            guild.me: PermissionOverwrite(read_messages=True, connect=True, speak=True, view_channel=True),
        }
        try:
            new_channel = await guild.create_voice_channel(
                name=new_name, category=category, overwrites=overwrites,
                reason="Auto-voice: new channel for member"
            )
            await member.move_to(new_channel, reason="Auto-voice: moved to new channel")
            logger.info(f"Created auto-voice channel '{new_name}' for {member}")
        except Exception as e:
            logger.error(f"Failed to create auto-voice channel: {e}")

    @tasks.loop(seconds=1)
    async def cleanup_empty_voice_channels(self):
        for guild in self.bot.guilds:
            settings = await self.bot.db.get_server_settings(guild.id)
            if not settings or not settings.get("voice_auto_enabled", False):
                continue
            suffix = settings.get("voice_auto_suffix", "s-channel")
            for channel in guild.voice_channels:
                if channel.name.endswith(suffix) and len(channel.members) == 0:
                    try:
                        await channel.delete(reason="Auto-voice: empty channel cleanup")
                        logger.info(f"Deleted empty auto-voice channel '{channel.name}' in {guild.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete empty channel '{channel.name}': {e}")

    @cleanup_empty_voice_channels.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="voice-auto-toggle", description="Enable or disable auto voice channel creation")
    @app_commands.describe(enabled="Whether to enable auto voice channels")
    async def voice_auto_toggle(self, interaction: Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, voice_auto_enabled=enabled)
        status = "enabled" if enabled else "disabled"
        await interaction.followup.send(
            f"✅ Auto voice channels {status}. Join the 'Create New' channel to create a private voice channel.",
            ephemeral=True
        )

    @app_commands.command(name="voice-auto-limit", description="Set the maximum number of auto voice channels")
    @app_commands.describe(limit="Maximum number of auto voice channels (1-30)")
    async def voice_auto_limit(self, interaction: Interaction, limit: int):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        if limit < 1 or limit > 30:
            await interaction.followup.send("❌ Limit must be between 1 and 30.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, voice_auto_limit=limit)
        await interaction.followup.send(f"✅ Auto voice channel limit set to {limit}", ephemeral=True)

    @app_commands.command(name="voice-auto-category", description="Set the category for auto voice channels")
    @app_commands.describe(category="Category where auto voice channels will be created")
    async def voice_auto_category(self, interaction: Interaction, category: CategoryChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, voice_auto_category_id=category.id)
        await interaction.followup.send(f"✅ Auto voice channels will be created in {category.mention}", ephemeral=True)

    @app_commands.command(name="voice-auto-trigger", description="Create the trigger channel for auto voice")
    async def voice_auto_trigger(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        settings = await self.bot.db.get_server_settings(interaction.guild.id)
        category_id = settings.get("voice_auto_category_id") if settings else None
        category = interaction.guild.get_channel(category_id) if category_id else None
        trigger_name = "➕ Create New Channel"
        if next((c for c in interaction.guild.voice_channels if c.name == trigger_name or c.name == "create-new"), None):
            await interaction.followup.send("⚠️ Trigger channel already exists!", ephemeral=True)
            return
        try:
            channel = await interaction.guild.create_voice_channel(
                name=trigger_name, category=category, reason="Auto-voice trigger channel"
            )
            await interaction.followup.send(
                f"✅ Trigger channel {channel.mention} created! Join this channel to create a private voice channel.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create trigger channel: {e}", ephemeral=True)


async def setup(bot):
    cog = AutoVoice(bot)
    cog.cleanup_empty_voice_channels.start()
    await bot.add_cog(cog)


async def teardown(bot, cog):
    cog.cleanup_empty_voice_channels.cancel()