"""
Logging cog - Audit log and action tracking.
"""
import logging
from datetime import datetime
from discord import (
    app_commands, Embed, Colour, Interaction, TextChannel, Member
)
from discord.ext import commands

logger = logging.getLogger("bot.cogs.logging")


class LoggingCog(commands.Cog):
    """Server logging and audit tracking."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        settings = await self.bot.db.get_server_settings(message.guild.id)
        if not settings or not settings.get("log_channel_id"):
            return
        channel = message.guild.get_channel(settings["log_channel_id"])
        if not channel or not isinstance(channel, TextChannel):
            return
        embed = Embed(title="🗑️ Message Deleted", color=Colour.red())
        embed.add_field(name="Author", value=f"{message.author.mention} ({message.author.id})", inline=True)
        embed.add_field(name="Channel", value=f"{message.channel.mention} ({message.channel.id})", inline=True)
        embed.add_field(name="Content", value=message.content[:500] or "*No text content*", inline=False)
        embed.set_footer(text=f"Deleted at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to log message delete: {e}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or after.author.bot or before.content == after.content:
            return
        settings = await self.bot.db.get_server_settings(before.guild.id)
        if not settings or not settings.get("log_channel_id"):
            return
        channel = before.guild.get_channel(settings["log_channel_id"])
        if not channel or not isinstance(channel, TextChannel):
            return
        embed = Embed(title="✏️ Message Edited", color=Colour.blue())
        embed.add_field(name="Author", value=f"{after.author.mention} ({after.author.id})", inline=True)
        embed.add_field(name="Channel", value=f"{after.channel.mention}", inline=True)
        embed.add_field(name="Before", value=before.content[:500] or "*Empty*", inline=False)
        embed.add_field(name="After", value=after.content[:500] or "*Empty*", inline=False)
        embed.set_footer(text=f"Edited at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to log message edit: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        if before.guild != after.guild:
            return
        settings = await self.bot.db.get_server_settings(before.guild.id)
        if not settings or not settings.get("log_channel_id"):
            return
        channel = before.guild.get_channel(settings["log_channel_id"])
        if not channel or not isinstance(channel, TextChannel):
            return
        if before.nick != after.nick:
            embed = Embed(title="📝 Nickname Changed", color=Colour.purple())
            embed.add_field(name="Member", value=f"{before.mention} ({before.id})", inline=True)
            embed.add_field(name="Old Nick", value=before.nick or "*None*", inline=True)
            embed.add_field(name="New Nick", value=after.nick or "*None*", inline=True)
            embed.set_footer(text=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to log nickname change: {e}")
        if set(before.roles) != set(after.roles):
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                embed = Embed(title="🎭 Roles Changed", color=Colour.gold())
                embed.add_field(name="Member", value=f"{before.mention}", inline=True)
                embed.add_field(name="Added", value=", ".join(r.mention for r in added) or "*None*", inline=True)
                embed.add_field(name="Removed", value=", ".join(r.mention for r in removed) or "*None*", inline=True)
                embed.set_footer(text=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Failed to log role change: {e}")

    @app_commands.command(name="logging-setup", description="Set up logging for the server")
    @app_commands.describe(channel="Channel to send logs to")
    async def logging_setup(self, interaction: Interaction, channel: TextChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, log_channel_id=channel.id)
        embed = Embed(title="✅ Logging Configured", color=Colour.green())
        embed.description = f"All events will be logged to {channel.mention}"
        embed.add_field(name="Logged Events", value="• Messages deleted/edited\n• Member joins/leaves\n• Role changes\n• Nickname changes\n• Moderation actions", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="logging-view", description="View recent server logs")
    async def logging_view(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        settings = await self.bot.db.get_server_settings(interaction.guild.id)
        embed = Embed(title="📊 Logging Status", color=Colour.blue())
        log_channel_id = settings.get("log_channel_id") if settings else None
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        if log_channel:
            embed.add_field(name="Log Channel", value=log_channel.mention, inline=True)
            embed.add_field(name="Status", value="✅ Active", inline=True)
        else:
            embed.add_field(name="Log Channel", value="Not configured", inline=True)
            embed.add_field(name="Status", value="❌ Inactive", inline=True)
            embed.set_footer(text="Use /logging-setup to configure logging")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LoggingCog(bot))