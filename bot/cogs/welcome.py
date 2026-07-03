"""
Welcome cog - Welcome and leave messages.
"""
import logging
from discord import app_commands, Embed, Colour, Interaction, TextChannel, Member
from discord.ext import commands

logger = logging.getLogger("bot.cogs.welcome")


class Welcome(commands.Cog):
    """Welcome and leave messages."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: Member):
        guild = member.guild
        settings = await self.bot.db.get_server_settings(guild.id)
        if not settings:
            return
        # Welcome message in channel
        if settings.get("welcome_enabled"):
            channel_id = settings.get("welcome_channel_id")
            if channel_id:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, TextChannel):
                    msg = settings.get("welcome_message", "Welcome {user} to {server}!")
                    msg = msg.replace("{user}", member.mention).replace("{server}", guild.name).replace("{member_count}", str(guild.member_count))
                    embed = Embed(description=msg, color=Colour.green())
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Failed to send welcome message: {e}")
            # Welcome DM
            dm_msg = settings.get("welcome_dm")
            if dm_msg:
                dm_msg = dm_msg.replace("{user}", member.name).replace("{server}", guild.name)
                try:
                    await member.send(dm_msg)
                except Exception:
                    pass
        # Assign default roles
        default_roles = settings.get("welcome_default_roles", "[]")
        if default_roles:
            import json
            try:
                role_ids = json.loads(default_roles)
                for role_id in role_ids:
                    role = guild.get_role(role_id)
                    if role:
                        try:
                            await member.add_roles(role, reason="Default welcome role")
                        except Exception as e:
                            logger.error(f"Failed to assign default role: {e}")
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: Member):
        guild = member.guild
        settings = await self.bot.db.get_server_settings(guild.id)
        if not settings:
            return
        channel_id = settings.get("leave_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, TextChannel):
            return
        msg = settings.get("leave_message", "{user} left {server}.")
        msg = msg.replace("{user}", member.display_name).replace("{server}", guild.name)
        embed = Embed(description=msg, color=Colour.red())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send leave message: {e}")

    @app_commands.command(name="welcome-channel", description="Set the welcome channel")
    @app_commands.describe(channel="Channel to send welcome messages in")
    async def welcome_channel(self, interaction: Interaction, channel: TextChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, welcome_channel_id=channel.id)
        await interaction.followup.send(f"✅ Welcome channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="welcome-message", description="Set the welcome message")
    @app_commands.describe(message="Welcome message ({user}, {server}, {member_count})")
    async def welcome_message(self, interaction: Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, welcome_message=message)
        await interaction.followup.send("✅ Welcome message updated", ephemeral=True)

    @app_commands.command(name="welcome-toggle", description="Enable or disable welcome messages")
    @app_commands.describe(enabled="Whether to enable welcome messages")
    async def welcome_toggle(self, interaction: Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, welcome_enabled=enabled)
        await interaction.followup.send(f"✅ Welcome messages {'enabled' if enabled else 'disabled'}", ephemeral=True)

    @app_commands.command(name="welcome-dm", description="Set welcome DM message")
    @app_commands.describe(message="DM message sent to new members ({user}, {server})")
    async def welcome_dm(self, interaction: Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, welcome_dm=message)
        await interaction.followup.send("✅ Welcome DM set", ephemeral=True)

    @app_commands.command(name="leave-channel", description="Set the leave message channel")
    @app_commands.describe(channel="Channel to send leave messages in")
    async def leave_channel(self, interaction: Interaction, channel: TextChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, leave_channel_id=channel.id)
        await interaction.followup.send(f"✅ Leave channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="leave-message", description="Set the leave message")
    @app_commands.describe(message="Leave message ({user}, {server})")
    async def leave_message(self, interaction: Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, leave_message=message)
        await interaction.followup.send("✅ Leave message updated", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))