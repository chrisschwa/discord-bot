"""
Leveling cog - XP and leveling system.
"""
import logging
import random
from discord import app_commands, Embed, Colour, Interaction, Member, Role
from discord.ext import commands

logger = logging.getLogger("bot.cogs.leveling")


class Leveling(commands.Cog):
    """XP and leveling system."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        settings = await self.bot.db.get_server_settings(message.guild.id)
        if not settings or not settings.get("leveling_enabled", True):
            return
        cooldown = settings.get("leveling_cooldown", 30)
        if cooldown:
            allowed = await self.bot.db.check_message_cooldown(message.guild.id, message.author.id, cooldown)
            if not allowed:
                return
        xp_amount = settings.get("leveling_xp", 10) or 10
        xp = xp_amount + random.randint(0, 5)
        old_level = await self.bot.db.get_user_level(message.guild.id, message.author.id)
        new_data = await self.bot.db.add_xp(message.guild.id, message.author.id, xp)
        if new_data:
            await self.bot.db.log_message_sent(message.guild.id, message.author.id)
            if new_data["level"] > old_level.get("level", 0):
                await self._send_level_up(message, new_data)
            # Check level rewards
            rewards = await self.bot.db.get_level_rewards(message.guild.id)
            for reward in rewards:
                if reward["level"] == new_data["level"]:
                    role = message.guild.get_role(reward["role_id"])
                    if role and not role in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason=f"Level {new_data['level']} reward")
                        except Exception as e:
                            logger.error(f"Failed to assign level reward role: {e}")

    async def _send_level_up(self, message, data):
        try:
            settings = await self.bot.db.get_server_settings(message.guild.id)
            member = message.author
            next_level_xp = data["level"] ** 2 * 100
            current_xp = data["xp"] - ((data["level"] - 1) ** 2 * 100) if data["level"] > 0 else data["xp"]
            progress_bar = self._create_progress_bar(current_xp, next_level_xp)
            embed = Embed(title="🎉 Level Up!", color=Colour.gold())
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(name="Level", value=str(data["level"]), inline=True)
            embed.add_field(name="XP", value=f"{data['xp']}", inline=True)
            embed.add_field(name="Rank", value=f"#{data['rank']}", inline=True)
            embed.add_field(name="Progress", value=progress_bar, inline=False)
            await message.channel.send(member.mention, embed=embed)
        except Exception as e:
            logger.error(f"Failed to send level up message: {e}")

    def _create_progress_bar(self, current, total, length=10):
        if total <= 0:
            return "██████████"
        filled = int(length * current / total)
        return "█" * filled + "░" * (length - filled)

    @app_commands.command(name="level", description="Check your level or another user's level")
    @app_commands.describe(user="User to check (default: yourself)")
    async def level(self, interaction: Interaction, user: Member = None):
        await interaction.response.defer(ephemeral=True)
        member = user or interaction.user
        data = await self.bot.db.get_user_level(interaction.guild.id, member.id)
        if not data:
            await interaction.followup.send(f"{member.display_name} hasn't earned any XP yet.", ephemeral=True)
            return
        next_level_xp = data["level"] ** 2 * 100
        current_xp = data["xp"] - ((data["level"] - 1) ** 2 * 100) if data["level"] > 0 else data["xp"]
        progress_bar = self._create_progress_bar(current_xp, next_level_xp)
        embed = Embed(title="📊 Level Info", color=Colour.blue())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="Level", value=str(data["level"]), inline=True)
        embed.add_field(name="XP", value=f"{data['xp']}", inline=True)
        embed.add_field(name="Rank", value=f"#{data['rank']}", inline=True)
        embed.add_field(name="Progress", value=progress_bar, inline=False)
        embed.add_field(name="Next Level", value=f"{next_level_xp} XP needed", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the XP leaderboard")
    async def leaderboard(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        leaderboard = await self.bot.db.get_leaderboard(interaction.guild.id, 10)
        if not leaderboard:
            await interaction.followup.send("No XP data yet. Start chatting!", ephemeral=True)
            return
        embed = Embed(title="🏆 Leaderboard", color=Colour.gold())
        medals = ["🥇", "🥈", "🥉"]
        for i, entry in enumerate(leaderboard):
            member = interaction.guild.get_member(entry["user_id"])
            name = member.mention if member else f"User #{entry['user_id']}"
            medal = medals[i] if i < 3 else f"**{i + 1}.**"
            embed.add_field(name=f"{medal} {name}", value=f"Level {entry['level']} · {entry['xp']} XP", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leveling-toggle", description="Enable or disable leveling")
    @app_commands.describe(enabled="Whether to enable leveling")
    async def leveling_toggle(self, interaction: Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, leveling_enabled=enabled)
        status = "enabled" if enabled else "disabled"
        await interaction.followup.send(f"✅ Leveling {status}", ephemeral=True)

    @app_commands.command(name="leveling-xp", description="Set XP earned per message")
    @app_commands.describe(xp="XP earned per message (1-50)")
    async def leveling_xp(self, interaction: Interaction, xp: int):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        xp = max(1, min(50, xp))
        await self.bot.db.set_server_settings(interaction.guild.id, leveling_xp=xp)
        await interaction.followup.send(f"✅ XP per message set to {xp}", ephemeral=True)

    @app_commands.command(name="leveling-cooldown", description="Set cooldown between XP messages")
    @app_commands.describe(seconds="Cooldown in seconds (5-120)")
    async def leveling_cooldown(self, interaction: Interaction, seconds: int):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        seconds = max(5, min(120, seconds))
        await self.bot.db.set_server_settings(interaction.guild.id, leveling_cooldown=seconds)
        await interaction.followup.send(f"✅ Leveling cooldown set to {seconds} seconds", ephemeral=True)

    @app_commands.command(name="leveling-reward", description="Set a role reward for reaching a level")
    @app_commands.describe(level="Level to unlock the role", role="Role to reward")
    async def leveling_reward(self, interaction: Interaction, level: int, role: Role):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.add_level_reward(interaction.guild.id, level, role.id)
        await interaction.followup.send(f"✅ Role {role.mention} awarded at level {level}", ephemeral=True)

    @app_commands.command(name="leveling-rewards", description="View all level rewards")
    async def leveling_rewards(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        rewards = await self.bot.db.get_level_rewards(interaction.guild.id)
        if not rewards:
            await interaction.followup.send("No level rewards configured.", ephemeral=True)
            return
        embed = Embed(title="🎁 Level Rewards", color=Colour.gold())
        for r in rewards:
            role = interaction.guild.get_role(r["role_id"])
            role_name = role.mention if role else f"Role #{r['role_id']}"
            embed.add_field(name=f"Level {r['level']}", value=role_name, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Leveling(bot))