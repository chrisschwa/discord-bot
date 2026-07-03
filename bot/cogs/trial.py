"""
Trial cog - Trial and promotion system for WoW raiding guilds.
"""
import logging
from datetime import datetime, timedelta
from discord import app_commands, Embed, Colour, Interaction, Member
from discord.ext import commands, tasks

logger = logging.getLogger("bot.cogs.trial")


class Trial(commands.Cog):
    """Trial and promotion system."""

    def __init__(self, bot):
        self.bot = bot
        self.cleanup_trials.start()

    @tasks.loop(minutes=30)
    async def cleanup_trials(self):
        """Check for and handle expired trials."""
        await self.bot.wait_until_ready()
        try:
            expired = await self.bot.db.get_expired_trials()
            for trial in expired:
                guild = self.bot.get_guild(trial["guild_id"])
                if not guild:
                    continue
                member = guild.get_member(trial["user_id"])
                reason = f"Trial expired after {trial['duration_days']} days"
                await self._end_trial(guild, member, "expired", reason)
        except Exception as e:
            logger.error(f"Error checking expired trials: {e}")

    async def _end_trial(self, guild, member, outcome, reason):
        """Remove trial role and clean up."""
        trial_role = guild.get_role(await self.bot.db.get_trial_role_id(guild.id))
        if trial_role and member and trial_role in member.roles:
            try:
                await member.remove_roles(trial_role, reason=reason)
            except Exception as e:
                logger.error(f"Failed to remove trial role: {e}")
        await self.bot.db.end_trial(guild.id, member.id if member else 0, outcome, reason)
        logger.info(f"Trial ended for {member.display_name if member else 'unknown'}: {outcome} - {reason}")
        # Log in log channel
        settings = await self.bot.db.get_server_settings(guild.id)
        if settings and settings.get("log_channel_id"):
            log_ch = guild.get_channel(settings["log_channel_id"])
            if log_ch:
                embed = Embed(title=f"Trial Ended: {outcome}", color=Colour.red() if outcome == "expired" else Colour.orange())
                if member:
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                embed.add_field(name="Outcome", value=outcome.capitalize(), inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                await log_ch.send(embed=embed)

    @app_commands.command(name="trial-start", description="Start a trial period for a member")
    @app_commands.describe(
        member="Member to put on trial",
        duration_days="Trial duration in days (default: 14)",
        reason="Reason for trial"
    )
    async def trial_start(self, interaction: Interaction, member: Member, duration_days: int = 14, reason: str = "New guild member"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        if member == interaction.user:
            await interaction.followup.send("❌ You cannot put yourself on trial.", ephemeral=True)
            return
        # Check if already on trial
        existing = await self.bot.db.get_trial(interaction.guild.id, member.id)
        if existing:
            await interaction.followup.send(f"❌ {member.mention} is already on trial.", ephemeral=True)
            return
        # Get or create Trial role
        trial_role_id = await self.bot.db.get_trial_role_id(interaction.guild.id)
        trial_role = None
        if trial_role_id:
            trial_role = interaction.guild.get_role(trial_role_id)
        if not trial_role:
            trial_role = next((r for r in interaction.guild.roles if r.name == "Trial"), None)
        if not trial_role:
            try:
                trial_role = await interaction.guild.create_role(name="Trial", color=Colour.blue(), hoist=True, mentionable=True)
                await self.bot.db.set_trial_role_id(interaction.guild.id, trial_role.id)
            except Exception as e:
                await interaction.followup.send(f"❌ Failed to create Trial role: {e}", ephemeral=True)
                return
        # Assign trial role
        try:
            await member.add_roles(trial_role, reason=f"Trial started: {reason}")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to assign Trial role: {e}", ephemeral=True)
            return
        # Record trial
        expires_at = datetime.now() + timedelta(days=duration_days)
        await self.bot.db.create_trial(interaction.guild.id, member.id, interaction.user.id, reason, expires_at, duration_days)
        # Send confirmation
        embed = Embed(title="🔵 Trial Started", color=Colour.blue())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="Duration", value=f"{duration_days} days", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Started by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        # DM member
        try:
            dm_embed = Embed(title="🔵 You are on Trial", color=Colour.blue())
            dm_embed.description = f"You have been placed on a **{duration_days}-day trial** in **{interaction.guild.name}**.\n\n**Reason:** {reason}\n**Expires:** <t:{int(expires_at.timestamp())}:R>\n\nUse `/trial-info` to check your trial status."
            await member.send(embed=dm_embed)
        except Exception:
            pass
        # Log
        await self._log_trial_action(interaction.guild.id, member.id, interaction.user.id, "started", reason)

    @app_commands.command(name="trial-pass", description="Promote a trial member to Raid-Alt")
    @app_commands.describe(
        member="Member to promote",
        reason="Reason for passing trial"
    )
    async def trial_pass(self, interaction: Interaction, member: Member, reason: str = "Successful trial"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        existing = await self.bot.db.get_trial(interaction.guild.id, member.id)
        if not existing:
            await interaction.followup.send(f"❌ {member.mention} is not on trial.", ephemeral=True)
            return
        # Remove Trial role
        trial_role_id = await self.bot.db.get_trial_role_id(interaction.guild.id)
        trial_role = interaction.guild.get_role(trial_role_id) if trial_role_id else None
        if not trial_role:
            trial_role = next((r for r in interaction.guild.roles if r.name == "Trial"), None)
        if trial_role and trial_role in member.roles:
            try:
                await member.remove_roles(trial_role, reason=f"Trial passed: {reason}")
            except Exception as e:
                logger.error(f"Failed to remove trial role: {e}")
        # Assign Raid-Alt role
        raid_alt = next((r for r in interaction.guild.roles if r.name == "Raid-Alt"), None)
        if raid_alt:
            try:
                await member.add_roles(raid_alt, reason=f"Promoted from trial: {reason}")
            except Exception as e:
                logger.error(f"Failed to assign Raid-Alt role: {e}")
        # End trial
        await self.bot.db.end_trial(interaction.guild.id, member.id, "passed", reason)
        # Confirmation
        embed = Embed(title="✅ Trial Passed!", color=Colour.green())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="Promoted to", value="Raid-Alt" if raid_alt else "None", inline=True)
        embed.add_field(name="By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        # DM
        try:
            dm_embed = Embed(title="✅ Trial Passed!", color=Colour.green())
            dm_embed.description = f"Congratulations! Your trial in **{interaction.guild.name}** has been **passed**.\n\n{raid_alt.mention if raid_alt else ''} **Reason:** {reason}"
            await member.send(embed=dm_embed)
        except Exception:
            pass
        await self._log_trial_action(interaction.guild.id, member.id, interaction.user.id, "passed", reason)

    @app_commands.command(name="trial-fail", description="Fail a trial member")
    @app_commands.describe(
        member="Member to fail",
        kick="Whether to kick the member",
        reason="Reason for failing trial"
    )
    async def trial_fail(self, interaction: Interaction, member: Member, kick: bool = False, reason: str = "Did not meet requirements"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        existing = await self.bot.db.get_trial(interaction.guild.id, member.id)
        if not existing:
            await interaction.followup.send(f"❌ {member.mention} is not on trial.", ephemeral=True)
            return
        # Remove Trial role
        trial_role_id = await self.bot.db.get_trial_role_id(interaction.guild.id)
        trial_role = interaction.guild.get_role(trial_role_id) if trial_role_id else None
        if not trial_role:
            trial_role = next((r for r in interaction.guild.roles if r.name == "Trial"), None)
        if trial_role and trial_role in member.roles:
            try:
                await member.remove_roles(trial_role, reason=f"Trial failed: {reason}")
            except Exception as e:
                logger.error(f"Failed to remove trial role: {e}")
        # End trial
        await self.bot.db.end_trial(interaction.guild.id, member.id, "failed", reason)
        # Kick if requested
        kicked = False
        if kick and interaction.user.guild_permissions.kick_members:
            try:
                await member.kick(reason=f"Trial failed: {reason}")
                kicked = True
            except Exception as e:
                logger.error(f"Failed to kick member: {e}")
        # Confirmation
        color = Colour.red() if kicked else Colour.orange()
        embed = Embed(title="❌ Trial Failed", color=color)
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="Kicked", value="Yes" if kicked else "No", inline=True)
        embed.add_field(name="By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        if not kicked:
            try:
                dm_embed = Embed(title="❌ Trial Failed", color=Colour.red())
                dm_embed.description = f"Your trial in **{interaction.guild.name}** has been **failed**.\n\n**Reason:** {reason}"
                await member.send(embed=dm_embed)
            except Exception:
                pass
        await self._log_trial_action(interaction.guild.id, member.id, interaction.user.id, "failed", reason)

    @app_commands.command(name="trial-info", description="Check your trial or another member's trial status")
    @app_commands.describe(member="Member to check (default: yourself)")
    async def trial_info(self, interaction: Interaction, member: Member = None):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        trial = await self.bot.db.get_trial(interaction.guild.id, target.id)
        if not trial:
            await interaction.followup.send(f"{target.mention} is not on trial.", ephemeral=True)
            return
        expires = datetime.fromisoformat(trial["expires_at"])
        remaining = expires - datetime.now()
        embed = Embed(title="🔵 Trial Info", color=Colour.blue())
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.add_field(name="Started", value=f"<t:{int(datetime.fromisoformat(trial['started_at']).timestamp())}:F>", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expires.timestamp())}:F>", inline=True)
        embed.add_field(name="Remaining", value=f"{remaining.days} days", inline=True)
        embed.add_field(name="Duration", value=f"{trial['duration_days']} days", inline=True)
        embed.add_field(name="Started by", value=target.mention if trial["started_by"] == target.id else f"User #{trial['started_by']}", inline=True)
        embed.add_field(name="Reason", value=trial["reason"], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="trial-list", description="List all members on trial")
    async def trial_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        trials = await self.bot.db.get_active_trials(interaction.guild.id)
        if not trials:
            await interaction.followup.send("No active trials.", ephemeral=True)
            return
        embed = Embed(title="🔵 Active Trials", color=Colour.blue())
        for trial in trials:
            member = interaction.guild.get_member(trial["user_id"])
            name = member.mention if member else f"User #{trial['user_id']}"
            expires = datetime.fromisoformat(trial["expires_at"])
            remaining = expires - datetime.now()
            embed.add_field(name=name, value=f"{remaining.days}d left · {trial['reason'][:50]}", inline=True)
        embed.set_footer(text=f"Total: {len(trials)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="trial-config", description="Configure trial settings")
    @app_commands.describe(
        setting="Setting to configure",
        value="Value to set"
    )
    @app_commands.choices(setting=[
        app_commands.Choice(name="Default Duration (days)", value="duration"),
        app_commands.Choice(name="Auto-expire action", value="auto_expire"),
    ])
    async def trial_config(self, interaction: Interaction, setting: str, value: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        if setting == "duration":
            try:
                days = int(value)
                await self.bot.db.set_server_settings(interaction.guild.id, trial_duration_days=days)
                await interaction.followup.send(f"✅ Default trial duration set to {days} days.", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)
        elif setting == "auto_expire":
            action = value.lower()
            if action in ("kick", "remove", "none"):
                await self.bot.db.set_server_settings(interaction.guild.id, trial_auto_expire_action=action)
                await interaction.followup.send(f"✅ Auto-expire action set to '{action}'.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Must be: kick, remove, or none.", ephemeral=True)

    async def _log_trial_action(self, guild_id, user_id, moderator_id, action, reason):
        """Log trial action."""
        settings = await self.bot.db.get_server_settings(guild_id)
        if settings and settings.get("log_channel_id"):
            guild = self.bot.get_guild(guild_id)
            if guild:
                log_ch = guild.get_channel(settings["log_channel_id"])
                if log_ch:
                    member = guild.get_member(user_id)
                    mod = guild.get_member(moderator_id)
                    embed = Embed(title=f"Trial Action: {action}", color=Colour.blue())
                    embed.add_field(name="Member", value=member.mention if member else f"#{user_id}", inline=True)
                    embed.add_field(name="By", value=mod.mention if mod else f"#{moderator_id}", inline=True)
                    embed.add_field(name="Action", value=action.capitalize(), inline=True)
                    embed.add_field(name="Reason", value=reason, inline=False)
                    await log_ch.send(embed=embed)


async def setup(bot):
    cog = Trial(bot)
    await bot.add_cog(cog)


async def teardown(bot, cog):
    cog.cleanup_trials.cancel()
