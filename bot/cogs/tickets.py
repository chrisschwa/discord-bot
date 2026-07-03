"""
Tickets cog - Support ticket system.
"""
import logging
from datetime import datetime
from discord import (
    app_commands, Embed, Colour, Interaction, Member, TextChannel,
    CategoryChannel, PermissionOverwrite, Permissions, ButtonStyle, Button, Role
)
from discord.ui import View, button
from discord.ext import commands

logger = logging.getLogger("bot.cogs.tickets")


class CloseTicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="Close Ticket", style=ButtonStyle.danger, emoji="🔒")
    async def close_button(self, interaction: Interaction, button: Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return

        guild_id = interaction.guild.id
        channel_id = interaction.channel.id

        try:
            ticket = await interaction.client.db.get_ticket(guild_id, channel_id)
            if not ticket:
                await interaction.edit_original_response(content="❌ This is not a valid ticket.")
                return
            if not interaction.user.guild_permissions.moderate_members and ticket["user_id"] != interaction.user.id:
                await interaction.edit_original_response(content="❌ Only the ticket creator or staff can close this ticket.")
                return

            transcript = ""
            try:
                async for msg in interaction.channel.history(limit=50):
                    if msg.author.bot:
                        continue
                    time = msg.created_at.strftime("%H:%M:%S")
                    transcript += f"[{time}] {msg.author.display_name}: {msg.content}\n"
            except Exception:
                transcript = "Failed to load transcript."

            await interaction.client.db.close_ticket(guild_id, channel_id, transcript)

            user = interaction.guild.get_member(ticket["user_id"])
            if user:
                try:
                    chunks = [transcript[i:i + 1900] for i in range(0, max(1, len(transcript) or 1), 1900)]
                    for chunk in chunks:
                        embed = Embed(title="🎫 Ticket Transcript", description=f"```{chunk}```", color=Colour.greyple())
                        await user.send(embed=embed)
                except Exception:
                    pass

            await interaction.edit_original_response(content="✅ Ticket closed. Transcript sent to ticket creator's DMs.")

            try:
                await interaction.channel.delete(reason="Ticket closed")
            except Exception as e:
                logger.error(f"Failed to delete ticket channel: {e}")

        except Exception as e:
            logger.error(f"Error closing ticket via button: {e}", exc_info=True)
            try:
                await interaction.channel.send("✅ Ticket closed!")
            except Exception:
                pass


class Tickets(commands.Cog):
    """Support ticket system."""

    def __init__(self, bot):
        self.bot = bot

    async def _create_ticket_channel(self, guild, user: Member, reason: str = None):
        settings = await self.bot.db.get_server_settings(guild.id)
        category_id = settings.get("ticket_category_id") if settings else None
        category = guild.get_channel(category_id) if category_id else None
        if not category:
            try:
                category = await guild.create_category_channel("🎫 Tickets", overwrites={guild.default_role: PermissionOverwrite(read_messages=False, view_channel=False)})
                await self.bot.db.set_server_settings(guild.id, ticket_category_id=category.id)
            except Exception as e:
                logger.error(f"Failed to create ticket category: {e}")
                raise
        ticket_num = len([ch for ch in category.text_channels if ch.name.startswith("ticket-")]) + 1
        channel_name = f"ticket-{user.name.lower()}-{ticket_num}"[:95]
        overwrites = {
            guild.default_role: PermissionOverwrite(read_messages=False, send_messages=False, view_channel=False),
            user: PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True, attach_files=True),
            guild.me: PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True, manage_messages=True),
        }
        ticket_role_id = settings.get("ticket_role_id") if settings else None
        if ticket_role_id:
            staff_role = guild.get_role(ticket_role_id)
            if staff_role:
                overwrites[staff_role] = PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True, manage_messages=True, embed_links=True, attach_files=True)
        else:
            for role in guild.roles:
                if role.permissions.moderate_members or role.permissions.administrator:
                    if role.name.lower() not in ("@everyone", "@here"):
                        overwrites[role] = PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True, manage_messages=True, embed_links=True, attach_files=True)
        channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites, reason=f"Ticket created by {user}")
        await self.bot.db.create_ticket(guild.id, channel.id, user.id, reason)
        embed = Embed(title="🎫 Support Ticket", color=Colour.blue())
        embed.description = f"Hi **{user.display_name}**! How can we help you?"
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        view = CloseTicketButton()
        await channel.send(user.mention, embed=embed, view=view)
        logger.info(f"Ticket created: {channel.name} by {user} in {guild.name}")
        return channel

    @app_commands.command(name="ticket-create", description="Create a new support ticket")
    @app_commands.describe(reason="Reason for creating the ticket")
    async def ticket_create(self, interaction: Interaction, reason: str = "No reason"):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user
        for channel in guild.text_channels:
            ticket = await self.bot.db.get_ticket(guild.id, channel.id)
            if ticket and ticket["status"] == "open" and ticket["user_id"] == user.id:
                await interaction.followup.send(f"You already have an open ticket: {channel.mention}", ephemeral=True)
                return
        try:
            channel = await self._create_ticket_channel(guild, user, reason)
            await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to create ticket: {e}")
            await interaction.followup.send(f"❌ Failed to create ticket: {e}", ephemeral=True)

    @app_commands.command(name="ticket-close", description="Close the current ticket")
    async def ticket_close(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        ticket = await self.bot.db.get_ticket(guild_id, channel_id)
        if not ticket:
            await interaction.followup.send("❌ This is not a ticket channel.", ephemeral=True)
            return
        if ticket["status"] == "closed":
            await interaction.followup.send("❌ This ticket is already closed.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.moderate_members and ticket["user_id"] != interaction.user.id:
            await interaction.followup.send("❌ Only the ticket creator or staff can close this ticket.", ephemeral=True)
            return
        transcript = ""
        try:
            async for msg in interaction.channel.history(limit=100):
                if msg.author.bot:
                    continue
                time = msg.created_at.strftime("%H:%M:%S")
                transcript += f"[{time}] {msg.author.display_name}: {msg.content}\n"
        except Exception:
            transcript = "Failed to load transcript."
        await self.bot.db.close_ticket(guild_id, channel_id, transcript)
        user = interaction.guild.get_member(ticket["user_id"])
        if user:
            try:
                embed = Embed(title="🎫 Ticket Transcript", color=Colour.greyple())
                chunks = [transcript[i:i + 1900] for i in range(0, max(1, len(transcript)), 1900)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(name=f"Part {i + 1}", value=f"```{chunk}```", inline=False)
                await user.send(embed=embed)
            except Exception:
                pass
        await interaction.followup.send("✅ Ticket closed. Transcript sent to the ticket creator.", ephemeral=True)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except Exception as e:
            logger.error(f"Failed to delete ticket channel: {e}")

    @app_commands.command(name="ticket-claim", description="Claim a ticket as a staff member")
    async def ticket_claim(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.followup.send("❌ Only staff can claim tickets.", ephemeral=True)
            return
        ticket = await self.bot.db.get_ticket(interaction.guild.id, interaction.channel.id)
        if not ticket:
            await interaction.followup.send("❌ This is not a ticket channel.", ephemeral=True)
            return
        if ticket["claimed_by"]:
            claimer = interaction.guild.get_member(ticket["claimed_by"])
            await interaction.followup.send(f"This ticket is already claimed by {claimer.mention if claimer else ticket['claimed_by']}.", ephemeral=True)
            return
        await self.bot.db.claim_ticket(interaction.guild.id, interaction.channel.id, interaction.user.id)
        embed = Embed(title="🎫 Ticket Claimed", color=Colour.green())
        embed.description = f"This ticket has been claimed by **{interaction.user.display_name}**."
        await interaction.channel.send(embed=embed)
        await interaction.followup.send("✅ Ticket claimed!", ephemeral=True)

    @app_commands.command(name="ticket-add", description="Add a member to the ticket")
    @app_commands.describe(member="Member to add")
    async def ticket_add(self, interaction: Interaction, member: Member):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.followup.send("❌ Only staff can add members to tickets.", ephemeral=True)
            return
        ticket = await self.bot.db.get_ticket(interaction.guild.id, interaction.channel.id)
        if not ticket:
            await interaction.followup.send("❌ This is not a ticket channel.", ephemeral=True)
            return
        try:
            await interaction.channel.set_permissions(member, read_messages=True, send_messages=True, view_channel=True)
            await interaction.followup.send(f"✅ Added {member.mention} to the ticket.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to add member: {e}", ephemeral=True)

    @app_commands.command(name="ticket-setup", description="Configure the ticket system")
    @app_commands.describe(category="Category for ticket channels", staff_role="Role that can access all tickets")
    async def ticket_setup(self, interaction: Interaction, category: CategoryChannel, staff_role: Role = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need Administrator permission.", ephemeral=True)
            return
        kwargs = {"ticket_category_id": category.id}
        if staff_role:
            kwargs["ticket_role_id"] = staff_role.id
        await self.bot.db.set_server_settings(interaction.guild.id, **kwargs)
        embed = Embed(title="✅ Ticket System Configured", color=Colour.green())
        embed.add_field(name="Category", value=category.mention, inline=True)
        embed.add_field(name="Staff Role", value=staff_role.mention if staff_role else "Admins/Mods", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))