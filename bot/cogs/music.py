"""
Music cog - Music playback commands for Discord voice channels.
"""
import logging
import asyncio
import functools
import discord
from discord import (
    app_commands, Embed, Colour, Interaction, Member, VoiceChannel
)
from discord.ext import commands

from bot.music.player import MusicPlayer, MusicManager, Track, LoopMode

logger = logging.getLogger("bot.cogs.music")


class Music(commands.Cog):
    """Music playback commands."""

    def __init__(self, bot):
        self.bot = bot
        self.music_manager = MusicManager()

    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        asyncio.create_task(self.music_manager.cleanup())

    def _check_voice_channel(self, interaction: Interaction) -> tuple:
        """Check if user is in a voice channel and bot has permissions."""
        member = interaction.user
        if not isinstance(member, Member):
            return None, "You must be in a Discord server to use this command."
        
        voice_state = member.voice
        if not voice_state or not voice_state.channel:
            return None, "You need to be in a voice channel first!"
        
        channel = voice_state.channel
        bot_permissions = channel.permissions_for(interaction.guild.me)
        if not bot_permissions.connect:
            return None, "I don't have permission to connect to your voice channel."
        if not bot_permissions.speak:
            return None, "I don't have permission to speak in your voice channel."
        
        return channel, None

    async def _get_music_channel(self, guild_id: int):
        """Get the configured music channel, or None."""
        settings = await self.bot.db.get_server_settings(guild_id)
        if settings and settings.get("music_channel_id"):
            channel = self.bot.get_channel(settings["music_channel_id"])
            if channel:
                return channel
        return None

    async def _send_to_channel(self, guild_id: int, interaction, content=None, embed=None):
        """Send message to music channel if configured, otherwise as followup."""
        music_channel = await self._get_music_channel(guild_id)
        if music_channel:
            try:
                await music_channel.send(content=content, embed=embed)
            except Exception:
                await interaction.followup.send(content=content, embed=embed)
        else:
            await interaction.followup.send(content=content, embed=embed)

    def _strip_playlist_params(self, url: str) -> str:
        """Strip playlist params (&list=, &index=, &v= after first) from URL."""
        from urllib.parse import urlparse, parse_qs, urlencode
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        # Keep only v, t, feature, hashtag, sparams
        keep = {"v", "t", "feature", "hashtag", "sparams"}
        filtered = {k: v for k, v in params.items() if k in keep}
        new_query = urlencode(filtered, doseq=True)
        new_parsed = parsed._replace(query=new_query)
        return new_parsed.geturl()

    def _is_url_like(self, text: str) -> bool:
        """Check if the input looks like a URL rather than a search query."""
        return text.startswith(("http://", "https://", "yt search:", "ytsearch:"))

    def _fetch_track_info_sync(self, query: str) -> Track:
        """Fetch track info from URL or search query using yt-dlp (runs in threadpool)."""
        import yt_dlp

        # Detect if input is a URL or a search query
        is_url = self._is_url_like(query)

        if is_url:
            # Strip playlist params so we get the single video info
            query = self._strip_playlist_params(query)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "default_search": "auto",
            "extract_flat": False,
            "socket_timeout": 30,
            "format": "bestaudio/best",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)

            if info is None:
                raise ValueError("yt-dlp returned no info for this query")

            if info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if entries:
                    first = entries[0]
                    title = first.get("title", "Unknown Playlist")
                    duration = first.get("duration", 0) or 0
                    # Store webpage_url so ffmpeg can re-resolve it at playback time
                    resolved_url = first.get("webpage_url") or first.get("url", query)
                else:
                    title = info.get("title", "Unknown Playlist")
                    duration = 0
                    resolved_url = query
            else:
                title = info.get("title", "Unknown Track")
                duration = info.get("duration", 0) or 0
                # Store webpage_url (original youtube URL) — NOT the signed videoplayback URL
                # Signed URLs expire and cause 403 Forbidden when ffmpeg tries to play them later.
                # FFmpeg can resolve youtube URLs natively at playback time.
                resolved_url = info.get("webpage_url") or info.get("url", query)

            thumbnail = info.get("thumbnail", "")
            source = info.get("extractor_key", "youtube").lower().replace("ie", "")

            return Track(
                title=title,
                url=resolved_url,
                duration=int(duration),
                requester_id=0,
                thumbnail=thumbnail,
                source=source,
            )

    async def _fetch_track_info(self, query: str) -> Track:
        """Fetch track info from URL or search query using yt-dlp (async wrapper with timeout)."""
        return await asyncio.wait_for(
            asyncio.to_thread(self._fetch_track_info_sync, query),
            timeout=60.0
        )

    async def _search_youtube(self, query: str) -> list:
        """Search YouTube for a query and return a list of results."""
        import yt_dlp

        search_query = f"ytsearch:{query}"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 30,
        }

        results = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if info and info.get("_type") == "playlist":
                for entry in info.get("entries", [])[:10]:
                    if entry and entry.get("title"):
                        results.append({
                            "title": entry.get("title", "Unknown"),
                            "url": entry.get("webpage_url") or entry.get("url", ""),
                            "duration": entry.get("duration", 0) or 0,
                            "thumbnail": entry.get("thumbnail", ""),
                        })
        return results

    @app_commands.command(name="music-play", description="Play a song by URL or search title")
    @app_commands.describe(query="YouTube/Spotify URL or song title to search")
    async def music_play(self, interaction: Interaction, query: str):
        channel, error = self._check_voice_channel(interaction)
        if error:
            await interaction.response.send_message(f"❌ {error}")
            return

        player = self.music_manager.get_player(interaction.guild.id)

        # Check if music channel is configured - if so, skip defer entirely
        # to avoid orphaned "thinking..." indicator when followup goes elsewhere
        music_channel = await self._get_music_channel(interaction.guild.id)
        if music_channel is None:
            # Responding in command channel - defer is safe (thinking clears on followup)
            await interaction.response.defer()

        if not player.voice_client or not player.voice_client.is_connected():
            joined = await player.join_voice_channel(interaction.guild, channel)
            if not joined:
                await interaction.followup.send("❌ Failed to join voice channel.")
                return

        try:
            track = await self._fetch_track_info(query)
            if track is None or not track.title or track.title == "Unknown Track":
                raise ValueError("Could not resolve track from query (video may be private, unlisted, or unavailable)")

            track.requester_id = interaction.user.id
            await player.add_to_queue(track)

            if not player.current and not player._task:
                asyncio.create_task(player.play_next(interaction.guild))

            search_note = " (search)" if not self._is_url_like(query) else ""
            embed = Embed(
                title=f"🎵 Added to Queue{search_note}",
                description=f"**{track.title}**",
                color=Colour.green(),
            )
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            embed.add_field(name="Duration", value=player._format_duration(track.duration), inline=True)
            embed.add_field(name="Position", value=f"#{player.queue_length}", inline=True)
            embed.add_field(name="Requested by", value=interaction.user.mention, inline=True)
            if player.current:
                embed.set_footer(text=f"Currently playing: {player.current.title}")

            await self._send_to_channel(interaction.guild.id, interaction, embed=embed)
            logger.info(f"Added to queue: {track.title} by {interaction.user}")

        except asyncio.TimeoutError:
            logger.error(f"Track fetch timed out for '{query}'")
            await interaction.followup.send("⏱ Track fetching timed out after 60 seconds.")
        except Exception as e:
            logger.error(f"Failed to fetch track info for '{query}': {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to fetch track: {e}")

    @app_commands.command(name="music-channel", description="Set the music response channel (Admin only)")
    @app_commands.describe(channel="Channel to send music responses to (defaults to current)")
    async def music_channel(self, interaction: Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permission.")
            return

        text_channel = channel or interaction.channel
        if not text_channel:
            await interaction.response.send_message("❌ You must use this command in a text channel.")
            return

        await self.bot.db.set_server_settings(
            interaction.guild.id,
            music_channel_id=text_channel.id
        )
        await interaction.response.send_message(f"🎵 Music responses will now be sent to {text_channel.mention}")

    @app_commands.command(name="music-channel-clear", description="Clear the fixed music channel (Admin only)")
    async def music_channel_clear(self, interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need Administrator permission.")
            return

        await self.bot.db.set_server_settings(
            interaction.guild.id,
            music_channel_id=None
        )
        await interaction.response.send_message("🎵 Music channel cleared. Responses will go to the command channel.")

    @app_commands.command(name="music-skip", description="Skip the current track")
    async def music_skip(self, interaction: Interaction):
        channel, error = self._check_voice_channel(interaction)
        if error:
            await interaction.response.send_message(f"❌ {error}")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is currently playing.")
            return

        skipped = player.current.title
        await player.skip()
        await self._send_to_channel(interaction.guild.id, interaction, content=f"⏭ Skipped **{skipped}**")

    @app_commands.command(name="music-pause", description="Pause the current track")
    async def music_pause(self, interaction: Interaction):
        channel, error = self._check_voice_channel(interaction)
        if error:
            await interaction.response.send_message(f"❌ {error}")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is currently playing.")
            return

        if await player.pause():
            await self._send_to_channel(interaction.guild.id, interaction, content="⏸ Paused playback")
        else:
            await self._send_to_channel(interaction.guild.id, interaction, content="❌ Playback is already paused or stopped.")

    @app_commands.command(name="music-resume", description="Resume paused playback")
    async def music_resume(self, interaction: Interaction):
        channel, error = self._check_voice_channel(interaction)
        if error:
            await interaction.response.send_message(f"❌ {error}")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is currently playing.")
            return

        if await player.resume():
            await self._send_to_channel(interaction.guild.id, interaction, content="▶ Resumed playback")
        else:
            await self._send_to_channel(interaction.guild.id, interaction, content="❌ Playback is not paused.")

    @app_commands.command(name="music-stop", description="Stop playback and leave voice channel")
    async def music_stop(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ You need Manage Channels permission.")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        was_playing = player.current is not None
        await player.leave_voice_channel()
        
        if was_playing:
            await interaction.response.send_message("⏹ Stopped playback and left voice channel")
        else:
            await interaction.response.send_message("👋 Left voice channel")

    @app_commands.command(name="music-queue", description="Show the current music queue")
    async def music_queue(self, interaction: Interaction):
        await interaction.response.defer()
        player = self.music_manager.get_player(interaction.guild.id)
        display = player.get_queue_display(interaction.user)
        
        if len(display) > 2000:
            display = display[:1997] + "..."
        
        await self._send_to_channel(interaction.guild.id, interaction, content=f"```{display}```")

    @app_commands.command(name="music-nowplaying", description="Show the currently playing track")
    async def music_nowplaying(self, interaction: Interaction):
        player = self.music_manager.get_player(interaction.guild.id)
        
        if not player.current:
            await interaction.response.send_message("❌ Nothing is currently playing.")
            return

        track = player.current
        embed = Embed(
            title="🎵 Now Playing",
            description=f"**{track.title}**",
            color=Colour.blurple(),
        )
        embed.add_field(name="Source", value=track.source.title(), inline=True)
        embed.add_field(name="Duration", value=player._format_duration(track.duration), inline=True)
        embed.add_field(name="Requested by", value=f"<@{track.requester_id}>", inline=True)
        embed.add_field(name="Volume", value=f"{player.volume}%", inline=True)
        embed.add_field(name="Loop", value=player.loop.value.title(), inline=True)
        
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        
        embed.set_footer(text=f"Queue: {player.queue_length} tracks remaining")
        await self._send_to_channel(interaction.guild.id, interaction, embed=embed)

    @app_commands.command(name="music-volume", description="Set the playback volume (0-100)")
    @app_commands.describe(level="Volume level (0-100)")
    async def music_volume(self, interaction: Interaction, level: int):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ You need Manage Channels permission.")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if not player.current:
            await interaction.response.send_message("❌ Nothing is currently playing.")
            return

        await player.set_volume(level)
        await self._send_to_channel(interaction.guild.id, interaction, content=f"🔊 Volume set to {level}%")

    @app_commands.command(name="music-shuffle", description="Shuffle the queue")
    async def music_shuffle(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ You need Manage Channels permission.")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if player.queue_length < 2:
            await interaction.response.send_message("❌ Need at least 2 tracks to shuffle.")
            return

        await player.shuffle()
        await self._send_to_channel(interaction.guild.id, interaction, content=f"🔀 Shuffled {player.queue_length} tracks in queue")

    @app_commands.command(name="music-loop", description="Toggle loop mode (off/track/queue)")
    @app_commands.describe(mode="Loop mode: off, track, or queue")
    async def music_loop(self, interaction: Interaction, mode: str):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ You need Manage Channels permission.")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        mode = mode.lower()

        if mode == "off":
            player.loop = LoopMode.OFF
            emoji = "❌"
        elif mode == "track":
            player.loop = LoopMode.TRACK
            emoji = "🔂"
        elif mode == "queue":
            player.loop = LoopMode.QUEUE
            emoji = "🔁"
        else:
            await interaction.response.send_message("❌ Invalid mode. Use: off, track, or queue")
            return

        await self._send_to_channel(interaction.guild.id, interaction, content=f"{emoji} Loop set to **{player.loop.value}**")

    @app_commands.command(name="music-remove", description="Remove a track from the queue")
    @app_commands.describe(position="Position in queue to remove (1-based)")
    async def music_remove(self, interaction: Interaction, position: int):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ You need Manage Channels permission.")
            return

        player = self.music_manager.get_player(interaction.guild.id)
        if position < 1 or position > player.queue_length:
            await interaction.response.send_message(
                f"❌ Invalid position. Queue has {player.queue_length} tracks."
            )
            return

        if await player.remove_from_queue(position):
            await self._send_to_channel(interaction.guild.id, interaction, content=f"🗑 Removed track at position {position}")
        else:
            await self._send_to_channel(interaction.guild.id, interaction, content="❌ Failed to remove track.")


async def setup(bot):
    await bot.add_cog(Music(bot))