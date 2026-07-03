"""
Help cog - Help, ping, and bot info commands.
"""
import logging
from discord import app_commands, Embed, Colour, Interaction
from discord.ext import commands

logger = logging.getLogger("bot.cogs.help")


class Help(commands.Cog):
    """Help and info commands."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Display all available commands")
    async def help(self, interaction: Interaction):
        embed = Embed(title="🤖 Bot Commands", color=Colour.blue())
        embed.description = "Here are all available commands grouped by category."

        embed.add_field(name="🏗️ Setup", value="/setup, /templates", inline=True)
        embed.add_field(name="👋 Welcome", value="/welcome-channel, /welcome-message, /welcome-toggle, /welcome-dm\n/leave-channel, /leave-message", inline=True)
        embed.add_field(name="🎭 Roles", value="/reactionrole-create, /reactionrole-add\n/reactionrole-list, /reactionrole-delete", inline=True)
        embed.add_field(name="🔊 Voice", value="/voice-auto-toggle, /voice-auto-limit\n/voice-auto-category, /voice-auto-trigger", inline=True)
        embed.add_field(name="🛡️ Moderation", value="/mod-ban, /mod-kick, /mod-mute, /mod-unmute\n/mod-warn, /mod-warnings, /mod-clear", inline=True)
        embed.add_field(name="🔒 AutoMod", value="/automod-setup, /automod-toggle\n/automod-words-add, /automod-words-remove, /automod-words-list", inline=True)
        embed.add_field(name="📊 Leveling", value="/level, /leaderboard, /leveling-toggle\n/leveling-xp, /leveling-cooldown, /leveling-reward", inline=True)
        embed.add_field(name="🎫 Tickets", value="/ticket-create, /ticket-close, /ticket-claim\n/ticket-add, /ticket-setup", inline=True)
        embed.add_field(name="📝 Logging", value="/logging-setup, /logging-view", inline=True)
        embed.add_field(name="ℹ️ Info", value="/help, /ping, /botinfo", inline=True)

        embed.set_footer(text="Use a command to see its description")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: Interaction):
        await interaction.response.send_message("🏓 Pinging...", ephemeral=True)
        latency = self.bot.latency * 1000
        await interaction.followup.send(
            f"🏓 Pong! Latency: **{latency:.1f}ms**", ephemeral=True
        )

    @app_commands.command(name="botinfo", description="Display bot information")
    async def botinfo(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = Embed(title="🤖 Bot Info", color=Colour.green())
        embed.add_field(name="Name", value=self.bot.user.display_name, inline=True)
        embed.add_field(name="ID", value=self.bot.user.id, inline=True)
        embed.add_field(name="Latency", value=f"{self.bot.latency * 1000:.1f}ms", inline=True)
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Python", value="3.x", inline=True)
        embed.add_field(name="discord.py", value=__import__("discord").__version__, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))