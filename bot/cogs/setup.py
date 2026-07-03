"""
Setup cog - Apply YAML templates to create server structures.
"""
import logging
import discord
from typing import Optional
from discord import (
    app_commands, Embed, Colour, Interaction, TextChannel, VoiceChannel,
    CategoryChannel, StageChannel, ForumChannel, Permissions,
    PermissionOverwrite, ChannelType
)
from discord.ext import commands

from templates.loader import TemplateLoader

logger = logging.getLogger("bot.cogs.setup")


class Setup(commands.Cog):
    """Server structure setup from YAML templates."""

    def __init__(self, bot):
        self.bot = bot
        self.loader = TemplateLoader()

    def _parse_channel_name(self, name: str) -> str:
        # Format: "📌|information" → "📌-information"
        # The emoji before | is kept as prefix with hyphen separator
        if "|" in name:
            parts = name.split("|", 1)
            prefix = parts[0].strip()  # emoji part
            channel_name = parts[1].strip()  # name part
            if prefix:
                return f"{prefix}-{channel_name}"
            return channel_name
        return name

    async def _create_category(self, guild: discord.Guild, category_data: dict) -> Optional[CategoryChannel]:
        name = self._parse_channel_name(category_data["name"])
        existing = next((c for c in guild.channels if c.name == name), None)
        if existing and isinstance(existing, CategoryChannel):
            logger.info(f"Category '{name}' already exists, skipping.")
            return existing
        try:
            category = await guild.create_category_channel(name, reason=f"Created by setup template")
            logger.info(f"Created category: {category.name}")
            return category
        except Exception as e:
            logger.error(f"Failed to create category '{name}': {e}")
            return None

    async def _create_channel(self, guild: discord.Guild, category: CategoryChannel, channel_data: dict):
        name = self._parse_channel_name(channel_data["name"])
        channel_type_str = channel_data.get("type", "text")
        type_map = {"text": ChannelType.text, "voice": ChannelType.voice, "announcement": ChannelType.news, "stage": ChannelType.stage_voice, "forum": ChannelType.forum}
        channel_type = type_map.get(channel_type_str, ChannelType.text)

        # Only match existing if same type and same category
        existing = next((c for c in guild.channels if c.name == name and c.type == channel_type and c.category == category), None)
        if existing:
            logger.info(f"Channel '{name}' already exists, updating...")
            # Update topic if provided
            channel_description = channel_data.get("description")
            if channel_description:
                try:
                    if channel_type in (ChannelType.text, ChannelType.news):
                        await existing.edit(topic=channel_description, reason="Template setup: update description")
                except Exception as e:
                    logger.warning(f"Failed to update description for {name}: {e}")
            await self._apply_channel_permissions(existing, guild, channel_data.get("permissions", {}))
            return existing
        try:
            if channel_type == ChannelType.text:
                channel = await guild.create_text_channel(name, category=category)
            elif channel_type == ChannelType.voice:
                channel = await guild.create_voice_channel(name, category=category)
            elif channel_type == ChannelType.news:
                channel = await guild.create_text_channel(name, category=category, type=ChannelType.news)
            elif channel_type == ChannelType.stage_voice:
                channel = await guild.create_stage_channel(name, category=category)
            elif channel_type == ChannelType.forum:
                channel = await guild.create_forum(name, category=category)
            else:
                return None
            logger.info(f"Created channel: {channel.name} (type: {channel_type_str})")
            # Set channel topic/description if provided in template
            channel_description = channel_data.get("description")
            if channel_description and hasattr(channel, "edit"):
                try:
                    if channel_type == ChannelType.text or channel_type == ChannelType.news:
                        await channel.edit(topic=channel_description, reason="Template setup: set description")
                except Exception as e:
                    logger.warning(f"Failed to set description for {channel.name}: {e}")
            # Apply permission overwrites from template
            await self._apply_channel_permissions(channel, guild, channel_data.get("permissions", {}))
            return channel
        except Exception as e:
            logger.error(f"Failed to create channel '{name}': {e}")
            return None

    async def _apply_channel_permissions(self, channel, guild: discord.Guild, perms_data: dict):
        """Apply permission overwrites from template to a channel."""
        for role_name, perms in perms_data.items():
            target = None
            if role_name == "@everyone":
                target = guild.default_role
            else:
                target = next((r for r in guild.roles if r.name == role_name), None)
            if not target:
                continue
            overwrite = PermissionOverwrite()
            for perm_name, value in perms.items():
                if value is not None and hasattr(overwrite, perm_name):
                    setattr(overwrite, perm_name, value)
            try:
                await channel.set_permissions(target, overwrite=overwrite, reason="Template setup")
            except Exception as e:
                logger.error(f"Failed to set permissions for {target.name} on {channel.name}: {e}")

    async def _create_role(self, guild: discord.Guild, role_data: dict) -> Optional[discord.Role]:
        name = role_data["name"]
        existing = next((r for r in guild.roles if r.name == name), None)
        raw_color = role_data.get("color", 0)
        color = Colour(min(raw_color, 16777215)) if raw_color else Colour.default()
        hoist = role_data.get("hoist", False)
        mentionable = role_data.get("mentionable", False)
        perms = Permissions(0)
        if role_data.get("permissions"):
            for perm_name, value in role_data["permissions"].items():
                if value and hasattr(perms, perm_name):
                    setattr(perms, perm_name, True)
        if existing:
            # Update existing role color, hoist, mentionable
            try:
                await existing.edit(
                    color=color,
                    hoist=hoist,
                    mentionable=mentionable,
                    permissions=perms,
                    reason="Template setup: update role"
                )
                logger.info(f"Role '{name}' updated (color/hoist/mentionable/perms).")
            except Exception as e:
                logger.error(f"Failed to update role '{name}': {e}")
            return existing
        try:
            role = await guild.create_role(name=name, color=color, hoist=hoist, mentionable=mentionable, permissions=perms)
            logger.info(f"Created role: {role.name}")
            return role
        except Exception as e:
            logger.error(f"Failed to create role '{name}': {e}")
            return None

    def _resolve_emoji(self, guild: discord.Guild, emoji_str: str):
        """Resolve emoji string to a reaction-compatible value."""
        import re
        # If in <:name:id> or <a:name:id> format
        custom_match = re.match(r'<a?:([^\s:]+):(\d+)>', emoji_str)
        if custom_match:
            name, emoji_id = custom_match.group(1), int(custom_match.group(2))
            emoji = guild.get_emoji(emoji_id)
            if emoji:
                return emoji
            return discord.PartialEmoji(name=name, id=emoji_id)
        # Strip colons (:name: format)
        if emoji_str.startswith(":") and emoji_str.endswith(":"):
            name = emoji_str.strip(":")
            # Try exact match
            emoji = next((e for e in guild.emojis if e.name == name), None)
            if emoji:
                return emoji
            # Try case-insensitive
            emoji = next((e for e in guild.emojis if e.name.lower() == name.lower()), None)
            if emoji:
                return emoji
            # Fallback: create PartialEmoji with a common guild emoji ID (may fail)
            logger.warning(f"Custom emoji '{name}' not found in guild, trying with first emoji's guild")
            # Can't resolve without an ID, return as-is and let Discord reject it
            return emoji_str
        # Unicode emoji - return as-is
        return emoji_str

    async def _apply_reaction_roles(self, guild: discord.Guild, template: dict, interaction: Interaction):
        """Apply reaction roles from template."""
        created = 0
        for rr_data in template.get("reaction_roles", []):
            channel_name = self._parse_channel_name(rr_data["channel"])
            channel = next((c for c in guild.text_channels if c.name == channel_name), None)
            if not channel:
                logger.warning(f"Reaction role channel '{channel_name}' not found, skipping.")
                continue
            message_content = rr_data.get("message", "")
            # Check if message already exists (by content match)
            existing_msg = None
            try:
                async for msg in channel.history(limit=50):
                    if msg.content == message_content:
                        existing_msg = msg
                        break
            except Exception:
                pass
            if existing_msg:
                msg = existing_msg
            else:
                try:
                    msg = await channel.send(message_content)
                except Exception as e:
                    logger.error(f"Failed to send reaction role message in {channel_name}: {e}")
                    continue
            try:
                for reaction_data in rr_data.get("reactions", []):
                    emoji_str = reaction_data["emoji"]
                    role_name = reaction_data["role"]
                    role = next((r for r in guild.roles if r.name == role_name), None)
                    if not role:
                        logger.warning(f"Role '{role_name}' not found for reaction role {emoji_str}, skipping.")
                        continue
                    resolved = self._resolve_emoji(guild, emoji_str)
                    try:
                        await msg.add_reaction(resolved)
                        # Store as the raw string for consistency
                        emoji_stored = str(resolved)
                        await self.bot.db.add_reaction_role(
                            guild.id, msg.channel.id, msg.id, emoji_stored, role.id
                        )
                        created += 1
                        logger.info(f"  Added reaction {emoji_stored} -> {role_name}")
                    except Exception as e:
                        logger.error(f"  Failed to add reaction {emoji_str} for {role_name}: {e}")
                logger.info(f"Reaction role message set up in {channel_name}")
            except Exception as e:
                logger.error(f"Failed to setup reaction roles: {e}")
        return created

    async def _apply_voice_trigger(self, guild: discord.Guild, template: dict):
        """Apply voice trigger channel from template."""
        voice_data = template.get("voice", {})
        if not voice_data:
            return 0
        trigger_name = voice_data.get("trigger_channel")
        if not trigger_name:
            return 0
        parsed_name = self._parse_channel_name(trigger_name)
        # Enable auto-voice in server settings
        try:
            await self.bot.db.set_server_settings(guild.id, voice_auto_enabled=True)
            logger.info(f"Voice auto-enabled for guild {guild.id} (trigger channel: {parsed_name})")
            return 1
        except Exception as e:
            logger.error(f"Failed to enable voice auto: {e}")
            return 0

    async def _apply_template(self, guild: discord.Guild, template: dict, interaction: Interaction):
        progress = await interaction.followup.send("⏳ Applying template... This may take a moment.", ephemeral=True)
        categories_created = 0
        channels_created = 0
        roles_created = 0
        reaction_roles_created = 0
        voice_triggered = 0
        for role_data in template.get("roles", []):
            if await self._create_role(guild, role_data):
                roles_created += 1
        for category_data in template.get("categories", []):
            category = await self._create_category(guild, category_data)
            if category:
                categories_created += 1
                for channel_data in category_data.get("channels", []):
                    if await self._create_channel(guild, category, channel_data):
                        channels_created += 1
        # Apply reaction roles
        reaction_roles_created = await self._apply_reaction_roles(guild, template, interaction)
        # Apply voice trigger
        voice_triggered = await self._apply_voice_trigger(guild, template)
        # Update server description if set in template
        server_description = template.get("description")
        if server_description:
            try:
                await guild.edit(description=server_description, reason="Template setup: update server description")
                logger.info(f"Server description updated for guild {guild.id}")
            except Exception as e:
                logger.warning(f"Could not update server description: {e}")
        await progress.edit(content=f"✅ **Template Applied!**\nCategories: {categories_created} | Channels: {channels_created} | Roles: {roles_created} | Reaction Roles: {reaction_roles_created} | Voice Trigger: {voice_triggered}")
        logger.info(f"Template '{template['name']}' applied to guild {guild.id}: {categories_created} categories, {channels_created} channels, {roles_created} roles, {reaction_roles_created} reaction roles")

    @app_commands.command(name="reaction-roles-recreate", description="Clear and recreate reaction roles from a template (only)")
    @app_commands.describe(template="Template to get reaction roles from")
    @app_commands.choices(template=[app_commands.Choice(name=name, value=name) for name in ["wow", "gaming", "community", "minimal"]])
    async def reaction_roles_recreate(self, interaction: Interaction, template: str):
        """Clear all reaction roles and recreate them from the specified template."""
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need the Administrator permission.", ephemeral=True)
            return
        template_data = self.loader.get_template(template)
        if not template_data:
            available = ", ".join(self.loader.list_templates())
            await interaction.followup.send(f"❌ Template '{template}' not found.\nAvailable: {available}", ephemeral=True)
            return
        # Step 1: Clear all existing reaction roles
        existing = await self.bot.db.get_reaction_roles(interaction.guild.id)
        for rr in existing:
            await self.bot.db.delete_reaction_role(rr["id"])
        # Step 2: Re-create from template
        created = await self._apply_reaction_roles(interaction.guild, template_data, interaction)
        await interaction.followup.send(
            f"✅ Cleared **{len(existing)}** old reaction roles and created **{created}** from template '{template}'.",
            ephemeral=True
        )

    @app_commands.command(name="setup", description="Setup server structure from a template")
    @app_commands.describe(template="Template name to apply")
    @app_commands.choices(template=[app_commands.Choice(name=name, value=name) for name in ["wow", "gaming", "community", "minimal"]])
    async def setup(self, interaction: Interaction, template: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need the Administrator permission to use this command.", ephemeral=True)
            return
        template_data = self.loader.get_template(template)
        if not template_data:
            available = ", ".join(self.loader.list_templates())
            await interaction.followup.send(f"❌ Template '{template}' not found.\nAvailable: {available}", ephemeral=True)
            return
        await self._apply_template(interaction.guild, template_data, interaction)

    @app_commands.command(name="setup-update", description="Re-apply template, optionally removing items not in template")
    @app_commands.describe(
        template="Template name to re-apply",
        force="Remove channels/roles/categories not in the template"
    )
    @app_commands.choices(template=[app_commands.Choice(name=name, value=name) for name in ["wow", "gaming", "community", "minimal"]])
    async def setup_update(self, interaction: Interaction, template: str, force: bool = False):
        """Update/re-apply template. With force=true, removes items no longer in template."""
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need the Administrator permission to use this command.", ephemeral=True)
            return
        template_data = self.loader.get_template(template)
        if not template_data:
            available = ", ".join(self.loader.list_templates())
            await interaction.followup.send(f"❌ Template '{template}' not found.\nAvailable: {available}", ephemeral=True)
            return

        roles_created = 0
        categories_created = 0
        channels_created = 0
        perms_updated = 0
        roles_deleted = 0
        channels_deleted = 0
        categories_deleted = 0
        created_channel_ids = set()  # Track IDs of channels just created/updated

        # Collect template names
        template_role_names = {r["name"] for r in template_data.get("roles", [])}
        template_cat_names = {self._parse_channel_name(c["name"]) for c in template_data.get("categories", [])}
        # Track which channels belong to which categories
        template_chan_by_cat = {}  # category_name -> set of channel names
        for cat_data in template_data.get("categories", []):
            cat_name = self._parse_channel_name(cat_data["name"])
            template_chan_by_cat[cat_name] = {self._parse_channel_name(ch_data["name"]) for ch_data in cat_data.get("channels", [])}

        # Re-create missing roles
        for role_data in template_data.get("roles", []):
            role = await self._create_role(interaction.guild, role_data)
            if role:
                roles_created += 1

        # Re-create missing categories and channels, re-apply permissions
        for category_data in template_data.get("categories", []):
            category = await self._create_category(interaction.guild, category_data)
            if category:
                categories_created += 1
                for channel_data in category_data.get("channels", []):
                    channel = await self._create_channel(interaction.guild, category, channel_data)
                    if channel:
                        channels_created += 1
                        created_channel_ids.add(channel.id)  # Track to avoid deleting
                    if channel_data.get("permissions"):
                        perms_updated += 1

        # FORCE MODE: Remove items not in template
        if force:
            # Delete roles not in template (skip @everyone and default)
            for role in list(interaction.guild.roles):
                if role == interaction.guild.default_role:
                    continue
                if role.name not in template_role_names:
                    try:
                        await role.delete(reason="Not in template (force update)")
                        roles_deleted += 1
                    except Exception:
                        pass

            # Refresh guild cache to pick up newly created channels
            await interaction.guild.fetch_channels() if hasattr(interaction.guild, 'fetch_channels') else None
            # Delete channels not in template (within template categories)
            for channel in list(interaction.guild.channels):
                if isinstance(channel, CategoryChannel):
                    continue
                # Skip channels we just created/updated
                if channel.id in created_channel_ids:
                    continue
                if channel.category and channel.category.name in template_chan_by_cat:
                    expected_channels = template_chan_by_cat[channel.category.name]
                    if channel.name not in expected_channels:
                        try:
                            await channel.delete(reason="Not in template (force update)")
                            channels_deleted += 1
                        except Exception:
                            pass

            # Delete empty categories not in template
            for category in list(interaction.guild.categories):
                if category.name not in template_cat_names:
                    try:
                        await category.delete(reason="Not in template (force update)")
                        categories_deleted += 1
                    except Exception:
                        pass

        embed = Embed(title="✅ Template Updated!", color=Colour.green())
        embed.add_field(name="Roles", value=f"{roles_created} updated" + (f", {roles_deleted} deleted" if force and roles_deleted else ""), inline=True)
        embed.add_field(name="Channels", value=f"{channels_created} updated" + (f", {channels_deleted} deleted" if force and channels_deleted else ""), inline=True)
        embed.add_field(name="Permissions", value=f"{perms_updated} updated", inline=True)
        if force and categories_deleted:
            embed.add_field(name="Categories Deleted", value=str(categories_deleted), inline=True)
        if force:
            embed.set_footer(text="Force mode: removed items not in template. Safe to re-run.")
        else:
            embed.set_footer(text="No duplicates created. Use /setup-update with force=true to remove extras.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setup-reset", description="Delete ALL channels and roles created by the bot (DANGER!)")
    async def setup_reset(self, interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permission.", ephemeral=True)
            return

        deleted_channels = 0
        deleted_categories = 0
        deleted_roles = 0

        # Delete all channels and categories
        for category in list(interaction.guild.categories):
            try:
                await category.delete(reason="Server reset")
                deleted_categories += 1
            except Exception:
                pass

        for channel in list(interaction.guild.channels):
            if not isinstance(channel, CategoryChannel):
                try:
                    await channel.delete(reason="Server reset")
                    deleted_channels += 1
                except Exception:
                    pass

        # Delete all non-default roles
        for role in list(interaction.guild.roles):
            if role.name in ("@everyone",) or role == interaction.guild.default_role:
                continue
            try:
                await role.delete(reason="Server reset")
                deleted_roles += 1
            except Exception:
                pass

        # Send confirmation via DM since the channel was deleted
        try:
            embed = Embed(title="🗑️ Server Reset!", color=Colour.red())
            embed.add_field(name="Categories", value=str(deleted_categories), inline=True)
            embed.add_field(name="Channels", value=str(deleted_channels), inline=True)
            embed.add_field(name="Roles", value=str(deleted_roles), inline=True)
            await interaction.user.send(embed=embed)
        except Exception:
            pass

        try:
            await interaction.response.send_message(
                f"🗑️ **Server Reset!**\nCategories: {deleted_categories}\nChannels: {deleted_channels}\nRoles: {deleted_roles}",
                ephemeral=True
            )
        except Exception:
            pass

    @app_commands.command(name="role-fix", description="Create missing leadership roles")
    @app_commands.describe(role_name="Role to create")
    @app_commands.choices(role_name=[
        app_commands.Choice(name="Guild-Master", value="Guild-Master"),
        app_commands.Choice(name="Officer", value="Officer"),
    ])
    async def role_fix(self, interaction: Interaction, role_name: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Need Administrator permission.", ephemeral=True)
            return
        existing = next((r for r in interaction.guild.roles if r.name == role_name), None)
        if existing:
            await interaction.followup.send(f"Role '{role_name}' already exists: {existing.mention}", ephemeral=True)
            return
        try:
            if role_name == "Guild-Master":
                perms = Permissions(0)
                perms.administrator = True
                role = await interaction.guild.create_role(name="Guild-Master", color=Colour.dark_red(), hoist=True, permissions=perms)
            elif role_name == "Officer":
                perms = Permissions(0)
                perms.kick_members = True
                perms.ban_members = True
                perms.manage_messages = True
                perms.moderate_members = True
                perms.manage_channels = True
                perms.manage_roles = True
                role = await interaction.guild.create_role(name="Officer", color=Colour.orange(), hoist=True, permissions=perms)
            else:
                return
            await interaction.followup.send(f"✅ Created {role.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)

    @app_commands.command(name="channel-create", description="Create a new channel manually")
    @app_commands.describe(
        name="Channel name",
        channel_type="Channel type",
        category="Category to create it in (optional)",
        nsfw="Mark channel as NSFW"
    )
    @app_commands.choices(channel_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice"),
        app_commands.Choice(name="Stage", value="stage"),
        app_commands.Choice(name="Forum", value="forum"),
    ])
    async def channel_create(self, interaction: Interaction, name: str, channel_type: str, category: CategoryChannel = None, nsfw: bool = False):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        try:
            if channel_type == "text":
                ch = await interaction.guild.create_text_channel(name, category=category, nsfw=nsfw)
            elif channel_type == "voice":
                ch = await interaction.guild.create_voice_channel(name, category=category)
                if nsfw:
                    await ch.edit(nsfw=True, reason="Created as NSFW by moderator")
            elif channel_type == "stage":
                ch = await interaction.guild.create_stage_channel(name, category=category)
                if nsfw:
                    await ch.edit(nsfw=True, reason="Created as NSFW by moderator")
            elif channel_type == "forum":
                ch = await interaction.guild.create_forum(name, category=category, nsfw=nsfw)
            else:
                return
            nsfw_label = " (NSFW)" if nsfw else ""
            await interaction.followup.send(f"✅ Created {ch.mention}{nsfw_label}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)

    @app_commands.command(name="channel-delete", description="Delete a channel")
    @app_commands.describe(channel="Channel to delete")
    async def channel_delete(self, interaction: Interaction, channel: TextChannel):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ You need Manage Channels permission.", ephemeral=True)
            return
        try:
            name = channel.name
            await channel.delete(reason="Deleted by moderator")
            await interaction.followup.send(f"✅ Deleted `{name}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)

    @app_commands.command(name="templates", description="List available server templates")
    async def templates(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        available = self.loader.list_templates()
        if not available:
            await interaction.followup.send("No templates available.", ephemeral=True)
            return
        embed = Embed(title="Available Templates", color=Colour.green())
        for name in available:
            template = self.loader.get_template(name)
            desc = template.get("description", "No description")
            channel_count = sum(len(cat.get("channels", [])) for cat in template.get("categories", []))
            role_count = len(template.get("roles", []))
            embed.add_field(name=name, value=f"**{template['name']}**\n{desc}\n`{channel_count}` channels · `{role_count}` roles", inline=False)
        embed.set_footer(text="Use /setup <template> to apply a template")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Setup(bot))