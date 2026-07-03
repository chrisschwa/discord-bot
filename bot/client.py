"""
Bot client - discord.py interaction client with cog loading.
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.database import Database

logger = logging.getLogger("bot")


class BotClient(commands.Bot):
    """Custom bot client with database and cog management."""

    def __init__(self, config: Config):
        # Define intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.voice_states = True
        intents.guild_reactions = True

        # Command prefix (secondary to slash commands)
        prefix = config.PREFIX

        super().__init__(
            command_prefix=prefix,
            intents=intents,
            help_command=None,
        )

        self.config = config
        self.db = Database()

        # Setup sync flag for syncing slash commands on startup
        self._sync_commands = True

    async def setup_hook(self):
        """Called when the bot is ready to load cogs."""
        # Initialize database
        await self.db.connect()
        logger.info("Database connected successfully.")

        # Load all cogs from bot/cogs/
        cog_dir = "bot.cogs"
        # Get the cogs package directory
        import importlib
        import os
        
        cogs_package = importlib.import_module(cog_dir)
        cogs_path = os.path.dirname(cogs_package.__file__)
        
        for filename in os.listdir(cogs_path):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = filename[:-3]  # Remove .py
                try:
                    await self.load_extension(f"{cog_dir}.{cog_name}")
                    logger.info(f"Loaded cog: {cog_name}")
                except Exception as e:
                    logger.error(f"Failed to load cog {cog_name}: {e}")

        logger.info("All cogs loaded.")

    @app_commands.command(name="debug-reactions", description="Debug: show all reaction roles")
    async def debug_reactions(self, interaction: discord.Interaction):
        """Debug command to test reaction role DB queries."""
        await interaction.response.defer(ephemeral=True)
        roles = await self.db.get_reaction_roles(interaction.guild.id)
        msg = f"Found {len(roles)} reaction roles in guild {interaction.guild.id}:\n"
        for r in roles:
            msg += f"  msg={r['message_id']}, emoji={r['emoji']}, role={r['role_id']}\n"
        msg += f"\nIntents: guild_reactions={self.intents.guild_reactions}"
        await interaction.followup.send(msg[:2000], ephemeral=True)

    async def on_ready(self):
        """Called when the bot has logged in."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")
        logger.info(f"INTENTS - guild_reactions: {self.intents.guild_reactions}, members: {self.intents.members}, message_content: {self.intents.message_content}")

        # Sync slash commands to guilds
        if self._sync_commands:
            try:
                for guild in self.guilds:
                    synced = await self.tree.sync(guild=guild)
                    logger.info(f"Synced {len(synced)} slash commands to {guild.name}")
                # Also sync globally (new global commands take up to 1hr to propagate)
                global_synced = await self.tree.sync()
                logger.info(f"Synced {len(global_synced)} slash commands globally")
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
            finally:
                self._sync_commands = False


    async def on_reaction_add(self, reaction, user):
        """CATCH ALL reaction events - raw handler."""
        try:
            logger.info(f"!!! RAW REACTION ADD: emoji={reaction.emoji} user={user.name}#{user.discriminator} msg={reaction.message.id} guild={reaction.message.guild.id if reaction.message.guild else 'DM'}")
        except Exception as e:
            logger.error(f"!!! ERROR in on_reaction_add: {e}")

    async def on_reaction_remove(self, reaction, user):
        """CATCH ALL reaction remove events - raw handler."""
        try:
            logger.info(f"!!! RAW REACTION REMOVE: emoji={reaction.emoji} user={user.name}#{user.discriminator} msg={reaction.message.id}")
        except Exception as e:
            logger.error(f"!!! ERROR in on_reaction_remove: {e}")

    async def on_message(self, message):
        """Event: message received."""
        if message.author.bot:
            return
        logger.info(f"MESSAGE from {message.author} in {message.channel.name}: {message.content[:50]}")
        
        # Process bot commands
        await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        """Global command error handler."""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, app_commands.AppCommandError):
            original = error.original
            if isinstance(original, discord.Forbidden):
                await ctx.send("❌ I don't have permission to do that.")
            elif isinstance(original, discord.NotFound):
                await ctx.send("❌ The resource was not found.")
            else:
                logger.error(f"Command error in {ctx.command}: {error}", exc_info=error)
                await ctx.send("❌ An error occurred while processing the command.", ephemeral=True)
        else:
            logger.error(f"Command error in {ctx.command}: {error}", exc_info=error)
            try:
                await ctx.send("❌ An error occurred while processing the command.", ephemeral=True)
            except Exception:
                pass

    async def close(self):
        """Clean shutdown."""
        await self.db.close()
        logger.info("Database connection closed.")
        await super().close()