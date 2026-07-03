"""
Moderation cog - Moderation commands and auto-moderation system.
"""
import logging
import re
from datetime import datetime, timedelta
from discord import (
    app_commands, Embed, Colour, Interaction, Member, TextChannel,
    Permissions, Message, User
)
from discord.ext import commands

logger = logging.getLogger("bot.cogs.moderation")

DEFAULT_BAD_WORDS = {
    "ass", "bitch", "damn", "dick", "fuck", "shit", "bastard",
    "piss", "crap", "hell", "whore", "slut"
}


class Moderation(commands.Cog):
    """Moderation commands and auto-moderation."""

    def __init__(self, bot):
        self.bot = bot
        self._spam_threshold = 5
        self._caps_ratio = 0.7

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        if message.author.bot or not message.guild:
            return
        settings = await self.bot.db.get_server_settings(message.guild.id)
        if not settings or not settings.get("automod_enabled", True):
            return
        rules = await self.bot.db.get_automod_rules(message.guild.id)
        content = message.content
        content_lower = content.lower()
        for rule in rules:
            action = rule.get("action", "delete")
            rule_type = rule.get("rule_type", "")
            should_delete = False
            if rule_type == "bad_words":
                bad_words = await self.bot.db.get_bad_words(message.guild.id)
                for word in bad_words:
                    if word in content_lower:
                        should_delete = True
                        break
            elif rule_type == "spam":
                count = await self.bot.db.get_recent_messages(message.guild.id, message.author.id, 5)
                if count >= self._spam_threshold:
                    should_delete = True
            elif rule_type == "caps":
                if len(content) > 10:
                    caps_count = sum(1 for c in content if c.isupper())
                    if caps_count / len(content) > self._caps_ratio:
                        should_delete = True
            elif rule_type == "invites":
                for pattern in [r"discord\.gg/\w+", r"discord\.com/invite/\w+"]:
                    if re.search(pattern, content_lower):
                        should_delete = True
                        break
            if should_delete:
                await self.bot.db.log_message_sent(message.guild.id, message.author.id)
                if action in ("delete", "delete_warn"):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                if action == "delete_warn":
                    try:
                        await message.author.send(
                            f"⚠️ Your message in **{message.guild.name}** was deleted for violating the server rules ({rule_type})."
                        )
                    except Exception:
                        pass
                await self._log_moderation_action(
                    message.guild.id, "automod", self.bot.user.id,
                    message.author.id, f"Auto-mod rule: {rule_type} → {action}", content[:500]
                )
                break

    async def _log_moderation_action(self, guild_id, action, moderator_id, target_id, reason, extra=None):
        settings = await self.bot.db.get_server_settings(guild_id)
        if not settings or not settings.get("log_channel_id"):
            return
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(settings["log_channel_id"])
        if not channel or not isinstance(channel, TextChannel):
            return
        moderator = guild.get_member(moderator_id) or self.bot.user
        target = guild.get_member(target_id)
        embed = Embed(title=f"🔨 {action.replace('_', ' ').title()}", color=Colour.orange())
        embed.add_field(name="Moderator", value=moderator.mention if moderator else f"ID: {moderator_id}", inline=True)
        embed.add_field(name="Target", value=target.mention if target else f"ID: {target_id}", inline=True)
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        if extra:
            embed.add_field(name="Message", value=f"``{extra}``", inline=False)
        embed.set_footer(text=f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send mod log: {e}")

    @app_commands.command(name="mod-ban", description="Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban", delete_days="Days of messages to delete (0-7)")
    async def mod_ban(self, interaction: Interaction, member: Member, reason: str = "No reason", delete_days: int = 0):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.ban_members:
            await interaction.followup.send("❌ You need Ban Members permission.", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send("❌ I can't ban someone with a role equal to or higher than mine.", ephemeral=True)
            return
        try:
            await member.ban(reason=reason, delete_message_days=max(0, min(7, delete_days)))
            await interaction.followup.send(f"✅ Banned {member.mention} — {reason}", ephemeral=True)
            await self._log_moderation_action(interaction.guild.id, "ban", interaction.user.id, member.id, reason)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to ban: {e}", ephemeral=True)

    @app_commands.command(name="mod-kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    async def mod_kick(self, interaction: Interaction, member: Member, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.kick_members:
            await interaction.followup.send("❌ You need Kick Members permission.", ephemeral=True)
            return
        try:
            await member.kick(reason=reason)
            await interaction.followup.send(f"✅ Kicked {member.mention} — {reason}", ephemeral=True)
            await self._log_moderation_action(interaction.guild.id, "kick", interaction.user.id, member.id, reason)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to kick: {e}", ephemeral=True)

    @app_commands.command(name="mod-mute", description="Mute a member (timeout)")
    @app_commands.describe(member="Member to mute", duration_minutes="Duration in minutes (max 40320)", reason="Reason")
    async def mod_mute(self, interaction: Interaction, member: Member, duration_minutes: int = 10, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.followup.send("❌ You need Moderate Members permission.", ephemeral=True)
            return
        duration = min(duration_minutes, 40320)
        try:
            await member.timeout(timeout=timedelta(minutes=duration), reason=reason)
            await interaction.followup.send(f"✅ Timed out {member.mention} for {duration} minutes — {reason}", ephemeral=True)
            await self._log_moderation_action(interaction.guild.id, "mute", interaction.user.id, member.id, f"{reason} ({duration} minutes)")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to mute: {e}", ephemeral=True)

    @app_commands.command(name="mod-unmute", description="Remove timeout from a member")
    @app_commands.describe(member="Member to unmute")
    async def mod_unmute(self, interaction: Interaction, member: Member):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.followup.send("❌ You need Moderate Members permission.", ephemeral=True)
            return
        try:
            await member.timeout(timeout=None, reason="Unmuted by moderator")
            await interaction.followup.send(f"✅ Removed timeout from {member.mention}", ephemeral=True)
            await self._log_moderation_action(interaction.guild.id, "unmute", interaction.user.id, member.id, "Timeout removed")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to unmute: {e}", ephemeral=True)

    @app_commands.command(name="mod-warn", description="Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    async def mod_warn(self, interaction: Interaction, member: Member, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.followup.send("❌ You need Moderate Members permission.", ephemeral=True)
            return
        await self.bot.db.add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        await interaction.followup.send(f"✅ Warned {member.mention} — {reason}", ephemeral=True)
        await self._log_moderation_action(interaction.guild.id, "warn", interaction.user.id, member.id, reason)

    @app_commands.command(name="mod-warnings", description="View a member's warnings")
    @app_commands.describe(member="Member to check warnings for")
    async def mod_warnings(self, interaction: Interaction, member: Member):
        await interaction.response.defer(ephemeral=True)
        warnings = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        if not warnings:
            await interaction.followup.send(f"✅ {member.display_name} has no warnings.", ephemeral=True)
            return
        embed = Embed(title=f"⚠️ Warnings for {member.display_name}", color=Colour.yellow())
        for w in warnings[:10]:
            mod = interaction.guild.get_member(w["moderator_id"])
            mod_name = mod.mention if mod else f"ID: {w['moderator_id']}"
            embed.add_field(name=f"Warning #{w['id']}", value=f"**Reason:** {w['reason'] or 'None'}\n**By:** {mod_name}", inline=False)
        embed.set_footer(text=f"Total warnings: {len(warnings)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mod-clear", description="Clear messages from a channel")
    @app_commands.describe(amount="Number of messages to clear (1-100)", channel="Channel to clear (default: current)")
    async def mod_clear(self, interaction: Interaction, amount: int, channel: TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.followup.send("❌ You need Manage Messages permission.", ephemeral=True)
            return
        target = channel or interaction.channel
        amount = max(1, min(100, amount))
        try:
            deleted = await target.clear(limit=amount)
            await interaction.followup.send(f"✅ Cleared {len(deleted)} messages from {target.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to clear messages: {e}", ephemeral=True)

    @app_commands.command(name="automod-setup", description="Setup auto-moderation rules")
    async def automod_setup(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        for rule_type, action in [("bad_words", "delete"), ("spam", "delete"), ("invites", "delete"), ("caps", "delete")]:
            await self.bot.db.add_automod_rule(interaction.guild.id, rule_type, action, None)
        for word in DEFAULT_BAD_WORDS:
            await self.bot.db.add_bad_word(interaction.guild.id, word)
        await interaction.followup.send("✅ Auto-moderation rules configured! Rules: bad_words, spam, invites, caps\nUse `/automod-words` to manage the bad words list.", ephemeral=True)

    @app_commands.command(name="automod-toggle", description="Enable or disable auto-moderation")
    @app_commands.describe(enabled="Whether to enable auto-moderation")
    async def automod_toggle(self, interaction: Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.set_server_settings(interaction.guild.id, automod_enabled=enabled)
        await interaction.followup.send(f"✅ Auto-moderation {'enabled' if enabled else 'disabled'}", ephemeral=True)

    @app_commands.command(name="automod-words-add", description="Add words to the bad words filter")
    @app_commands.describe(words="Words to block (comma separated)")
    async def automod_words_add(self, interaction: Interaction, words: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        word_list = [w.strip().lower() for w in words.split(",") if w.strip()]
        for word in word_list:
            await self.bot.db.add_bad_word(interaction.guild.id, word)
        await interaction.followup.send(f"✅ Added {len(word_list)} words to the filter", ephemeral=True)

    @app_commands.command(name="automod-words-remove", description="Remove a word from the bad words filter")
    @app_commands.describe(word="Word to remove")
    async def automod_words_remove(self, interaction: Interaction, word: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        await self.bot.db.remove_bad_word(interaction.guild.id, word)
        await interaction.followup.send(f"✅ Removed '{word}' from the filter", ephemeral=True)

    @app_commands.command(name="automod-words-list", description="List blocked words")
    async def automod_words_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        words = await self.bot.db.get_bad_words(interaction.guild.id)
        if not words:
            await interaction.followup.send("No blocked words configured.", ephemeral=True)
            return
        embed = Embed(title="🚫 Blocked Words", color=Colour.red())
        for i in range(0, len(words), 25):
            chunk = words[i:i + 25]
            embed.add_field(name=f"Words ({i+1}-{i+len(chunk)})", value=", ".join(f"`{w}`" for w in chunk), inline=False)
        embed.set_footer(text=f"Total: {len(words)} words")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))