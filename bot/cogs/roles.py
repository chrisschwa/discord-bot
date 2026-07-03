"""
Reaction Roles cog - Assign roles based on message reactions.
"""
import logging
import re
import discord
from discord import (
    app_commands, Embed, Colour, Interaction, TextChannel, Member, User,
    Reaction, Role
)
from discord.ext import commands

logger = logging.getLogger("bot.cogs.roles")


class ReactionRoles(commands.Cog):
    """Reaction-based role assignment system."""

    def __init__(self, bot):
        self.bot = bot

    async def _resolve_emoji(self, guild: discord.Guild, emoji_str: str):
        """Resolve emoji string. Returns discord.Emoji for custom emojis, or str for unicode emojis."""
        logger.info(f"_resolve_emoji called with: '{emoji_str}' (len={len(emoji_str)})")

        # If already in <:name:id> or <a:name:id> format
        custom_match = re.match(r'<a?:([^\s:]+):(\d+)>', emoji_str)
        if custom_match:
            name, emoji_id = custom_match.group(1), int(custom_match.group(2))
            # Try guild cache first
            emoji = guild.get_emoji(emoji_id)
            if emoji:
                logger.info(f"  -> Found in guild cache: {emoji.name}")
                return emoji
            # Not in cache - try fetching from API
            try:
                fetched = await guild.fetch_emoji(emoji_id)
                logger.info(f"  -> Fetched from API: {fetched.name}")
                return fetched
            except discord.NotFound:
                logger.info(f"  -> Emoji {emoji_id} not in guild, creating PartialEmoji")
            # PartialEmoji works for any emoji the bot can access, even from other servers
            return discord.PartialEmoji(name=name, id=emoji_id)

        # Strip colons if present (:name: format)
        has_colons = emoji_str.startswith(":") and emoji_str.endswith(":")
        name = emoji_str.strip(":")

        logger.info(f"  Stripped name: '{name}' (has_colons={has_colons})")

        # Try exact match first
        emoji = next((e for e in guild.emojis if e.name == name), None)
        if emoji:
            logger.info(f"  -> Found exact match: {emoji.name}")
            return emoji

        # Try case-insensitive
        emoji = next((e for e in guild.emojis if e.name.lower() == name.lower()), None)
        if emoji:
            logger.info(f"  -> Found case-insensitive match: {emoji.name}")
            return emoji

        # If it had colons or is alphabetic and > 1 char, it's a custom emoji that wasn't found
        if has_colons or (name.isalpha() and len(name) > 1):
            available = ", ".join([e.name for e in guild.emojis[:10]])
            raise ValueError(f"Custom emoji '{name}' not found in this server.\n"
                           f"First 10 available: {available or '(none)'}\n"
                           f"Copy-paste the emoji directly, or use a unicode emoji.")

        # Assume it's a unicode emoji
        logger.info(f"  -> Treating as unicode emoji")
        return emoji_str

    async def _handle_reaction_add(self, reaction: Reaction, user: User):
        if user.bot or not reaction.message.guild:
            return
        guild_id = reaction.message.guild.id
        message_id = reaction.message.id
        emoji = str(reaction.emoji)
        logger.info(f"Reaction add: guild={guild_id}, msg={message_id}, emoji='{emoji}'")
        
        # Try exact match first
        role_data = await self.bot.db.get_reaction_role(guild_id, message_id, emoji)
        
        # If not found, try case-insensitive / normalized matching
        if not role_data:
            all_roles = await self.bot.db.get_reaction_roles(guild_id)
            for rr in all_roles:
                if rr["message_id"] == message_id:
                    stored_emoji = rr["emoji"]
                    logger.info(f"  Comparing stored '{stored_emoji}' with reaction '{emoji}'")
                    # Normalize both: strip <> for custom emojis, lowercase
                    if stored_emoji.lower().strip('<>') == emoji.lower().strip('<>'):
                        role_data = rr
                        logger.info(f"  -> Matched via normalization!")
                        break
        
        if not role_data:
            logger.info(f"  -> No reaction role found for this emoji")
            return
        guild = reaction.message.guild
        role = guild.get_role(role_data["role_id"])
        member = guild.get_member(user.id)
        if not role or not member:
            logger.warning(f"Role or member not found: role={role_data['role_id']}, member={user.id}")
            return
        
        # Check if bot can assign this role
        bot_role = guild.me.top_role
        if role >= bot_role:
            logger.warning(f"Cannot assign role '{role.name}' - it's at or above my highest role")
            return
        
        try:
            await member.add_roles(role, reason="Reaction role")
            logger.info(f"Assigned role '{role.name}' to {member} via reaction")
        except discord.Forbidden:
            logger.error(f"Missing permission to assign role '{role.name}' to {member}")
        except Exception as e:
            logger.error(f"Failed to assign role: {e}")

    async def _handle_reaction_remove(self, reaction: Reaction, user: User):
        if user.bot or not reaction.message.guild:
            return
        guild_id = reaction.message.guild.id
        message_id = reaction.message.id
        emoji = str(reaction.emoji)
        logger.info(f"Reaction remove: guild={guild_id}, msg={message_id}, emoji='{emoji}'")
        
        role_data = await self.bot.db.get_reaction_role(guild_id, message_id, emoji)
        
        if not role_data:
            all_roles = await self.bot.db.get_reaction_roles(guild_id)
            for rr in all_roles:
                if rr["message_id"] == message_id:
                    stored_emoji = rr["emoji"]
                    if stored_emoji.lower().strip('<>') == emoji.lower().strip('<>'):
                        role_data = rr
                        break
        
        if not role_data:
            return
        guild = reaction.message.guild
        role = guild.get_role(role_data["role_id"])
        member = guild.get_member(user.id)
        if not role or not member:
            logger.warning(f"Role or member not found for remove: role={role_data['role_id']}, member={user.id}")
            return
        
        # Check if bot can remove this role
        bot_role = guild.me.top_role
        if role >= bot_role:
            logger.warning(f"Cannot remove role '{role.name}' - it's at or above my highest role")
            return
        
        try:
            await member.remove_roles(role, reason="Reaction role removed")
            logger.info(f"Removed role '{role.name}' from {member} via reaction")
        except discord.Forbidden:
            logger.error(f"Missing permission to remove role '{role.name}' from {member}")
        except Exception as e:
            logger.error(f"Failed to remove role: {e}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: Reaction, user: User):
        await self._handle_reaction_add(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: Reaction, user: User):
        await self._handle_reaction_remove(reaction, user)

    @app_commands.command(name="reactionrole-create", description="Create a new reaction role setup")
    @app_commands.describe(channel="Channel where the message will be posted", message="Message content", emoji="Emoji to react with", role="Role to assign")
    async def reactionrole_create(self, interaction: Interaction, channel: TextChannel, message: str, emoji: str, role: Role):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        try:
            resolved_emoji = await self._resolve_emoji(interaction.guild, emoji)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
        emoji_display = str(resolved_emoji)
        try:
            sent_message = await channel.send(message)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to send message: {e}", ephemeral=True)
            return
        try:
            await sent_message.add_reaction(resolved_emoji)
        except discord.HTTPException as e:
            if e.status == 400:
                await interaction.followup.send(
                    f"❌ Unknown emoji. Please copy-paste the emoji directly from the server.\n"
                    f"Given: `{emoji}`\nResolved: `{emoji_display}`",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Failed to add reaction: {e}", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to add reaction: {e}", ephemeral=True)
            return
        await self.bot.db.add_reaction_role(interaction.guild.id, sent_message.channel.id, sent_message.id, emoji_display, role.id)
        embed = Embed(title="✅ Reaction Role Created", color=Colour.green())
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Emoji", value=emoji, inline=True)
        embed.set_footer(text="React to the message to get the role!")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="reactionrole-add", description="Add reaction role to existing message")
    @app_commands.describe(message_id="ID of the message", emoji="Emoji to react with", role="Role to assign")
    async def reactionrole_add(self, interaction: Interaction, message_id: str, emoji: str, role: Role):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        try:
            msg_id = int(message_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid message ID.", ephemeral=True)
            return
        message = None
        for ch in interaction.guild.text_channels:
            try:
                message = await ch.fetch_message(msg_id)
                break
            except (discord.NotFound, discord.Forbidden):
                continue
        if not message:
            await interaction.followup.send("❌ Message not found.", ephemeral=True)
            return
        try:
            resolved_emoji = await self._resolve_emoji(interaction.guild, emoji)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
        emoji_display = str(resolved_emoji)
        try:
            await message.add_reaction(resolved_emoji)
        except discord.HTTPException as e:
            if e.status == 400:
                await interaction.followup.send(
                    f"❌ Unknown emoji. Please copy-paste the emoji directly from the server.\n"
                    f"Given: `{emoji}`\nResolved: `{emoji_display}`",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Failed to add reaction: {e}", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to add reaction: {e}", ephemeral=True)
            return
        await self.bot.db.add_reaction_role(interaction.guild.id, message.channel.id, message.id, emoji_display, role.id)
        await interaction.followup.send(f"✅ Reaction role added! {emoji_display} -> {role.mention}", ephemeral=True)

    @app_commands.command(name="reactionrole-list", description="List all reaction roles in the server")
    async def reactionrole_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        roles = await self.bot.db.get_reaction_roles(interaction.guild.id)
        if not roles:
            await interaction.followup.send("No reaction roles configured.", ephemeral=True)
            return
        # Group by channel for clean display
        by_channel = {}
        for rr in roles:
            ch = interaction.guild.get_channel(rr["channel_id"])
            ch_name = ch.name.replace("-", "").lower() if ch else "unknown"
            if ch_name not in by_channel:
                by_channel[ch_name] = {"display_name": ch.mention if ch else "unknown", "roles": []}
            role = interaction.guild.get_role(rr["role_id"])
            by_channel[ch_name]["roles"].append((rr, role))
        # Build a single clean embed
        embed = Embed(title="🎭 Self-Assignable Roles", color=Colour.blurple(), description="React to get a role · React again to remove it")
        for ch_key, data in by_channel.items():
            lines = []
            for rr, role in data["roles"]:
                role_name = role.name if role else "~~missing~~"
                lines.append(f"{rr['emoji']} {role_name}")
            role_list = "\n".join(lines)
            embed.add_field(
                name=data["display_name"],
                value=role_list,
                inline=True
            )
        embed.set_footer(text=f"{len(roles)} roles configured")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="reactionrole-change-emoji", description="Change the emoji of an existing reaction role")
    @app_commands.describe(role="Role to change the emoji for", new_emoji="New emoji to use")
    async def reactionrole_change_emoji(self, interaction: Interaction, role: Role, new_emoji: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        all_roles = await self.bot.db.get_reaction_roles(interaction.guild.id)
        target = next((r for r in all_roles if r["role_id"] == role.id), None)
        if not target:
            await interaction.followup.send(f"❌ No reaction role found for **{role.name}**.", ephemeral=True)
            return
        old_emoji = target["emoji"]
        try:
            resolved_new = await self._resolve_emoji(interaction.guild, new_emoji)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
        new_emoji_display = str(resolved_new)
        # Update DB
        await self.bot.db.update_reaction_role_emoji(target["id"], new_emoji_display)
        # Update reactions on the message
        ch = interaction.guild.get_channel(target["channel_id"])
        if ch:
            try:
                message = await ch.fetch_message(target["message_id"])
                try:
                    await message.remove_reaction(old_emoji, self.bot.user)
                except Exception:
                    pass
                await message.add_reaction(resolved_new)
                # Rebuild message content
                msg_roles = [r for r in all_roles if r["channel_id"] == target["channel_id"] and r["message_id"] == target["message_id"]]
                if msg_roles:
                    parts = []
                    for mr in msg_roles:
                        r_emoji = new_emoji_display if mr["id"] == target["id"] else mr["emoji"]
                        r_role = interaction.guild.get_role(mr["role_id"])
                        r_name = r_role.name if r_role else "unknown"
                        parts.append(f"{r_emoji} {r_name}")
                    await message.edit(content=" | ".join(parts))
            except Exception as e:
                logger.error(f"Failed to update message: {e}")
        await interaction.followup.send(f"✅ Changed **{role.name}**: {old_emoji} -> {new_emoji_display}", ephemeral=True)

    @app_commands.command(name="reactionrole-clear-all", description="Delete ALL reaction roles in the server")
    async def reactionrole_clear_all(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        roles = await self.bot.db.get_reaction_roles(interaction.guild.id)
        for rr in roles:
            await self.bot.db.delete_reaction_role(rr["id"])
        await interaction.followup.send(f"✅ Deleted **{len(roles)}** reaction roles. Use `/setup-update` to recreate them.", ephemeral=True)

    @app_commands.command(name="reactionrole-recreate", description="Recreate all self-role messages that were deleted")
    @app_commands.describe(channel="Channel to send all messages to (optional, uses original if set)")
    async def reactionrole_recreate(self, interaction: Interaction, channel: TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        roles = await self.bot.db.get_reaction_roles(interaction.guild.id)
        if not roles:
            await interaction.followup.send("No reaction roles configured.", ephemeral=True)
            return
        # Group by message
        by_message = {}
        for rr in roles:
            msg_key = (rr["channel_id"], rr["message_id"])
            if msg_key not in by_message:
                by_message[msg_key] = {"channel_id": rr["channel_id"], "roles": []}
            by_message[msg_key]["roles"].append(rr)
        recreated = 0
        failed = 0
        for msg_key, data in by_message.items():
            target_ch = channel or interaction.guild.get_channel(data["channel_id"])
            if not target_ch:
                failed += 1
                continue
            # Build content
            parts = []
            for rr in data["roles"]:
                role = interaction.guild.get_role(rr["role_id"])
                role_name = role.name if role else "unknown"
                parts.append(f"{rr['emoji']} {role_name}")
            content = " | ".join(parts)
            try:
                new_msg = await target_ch.send(content)
                # Add reactions
                for rr in data["roles"]:
                    try:
                        resolved = await self._resolve_emoji(interaction.guild, rr["emoji"])
                        await new_msg.add_reaction(resolved)
                        # Update DB with new message ID
                        await self.bot.db.update_reaction_role_message_id(rr["id"], new_msg.channel.id, new_msg.id)
                    except Exception:
                        pass
                recreated += 1
            except Exception:
                failed += 1
        await interaction.followup.send(
            f"✅ Recreated **{recreated}** self-role messages. {failed} failed (channel not found).",
            ephemeral=True
        )

    @app_commands.command(name="reactionrole-delete", description="Delete a reaction role")
    @app_commands.describe(role="Role to remove from self-assign")
    async def reactionrole_delete(self, interaction: Interaction, role: Role):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("❌ You need Manage Roles permission.", ephemeral=True)
            return
        all_roles = await self.bot.db.get_reaction_roles(interaction.guild.id)
        target = next((r for r in all_roles if r["role_id"] == role.id), None)
        if not target:
            await interaction.followup.send(f"❌ No reaction role found for **{role.name}**.", ephemeral=True)
            return
        ch = interaction.guild.get_channel(target["channel_id"])
        if ch:
            try:
                message = await ch.fetch_message(target["message_id"])
                try:
                    await message.remove_reaction(target["emoji"], self.bot.user)
                except Exception:
                    pass
            except Exception:
                pass
        await self.bot.db.delete_reaction_role(target["id"])
        await interaction.followup.send(f"✅ Removed **{role.name}** from self-assign roles.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))