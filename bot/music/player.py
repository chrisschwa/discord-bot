"""
Music player - Queue-based FFmpeg audio player for Discord voice channels.
"""
import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlencode

import discord
from discord import VoiceClient, VoiceState
import yt_dlp

logger = logging.getLogger("bot.music")


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


@dataclass
class Track:
    """A single track in the music queue."""
    title: str
    url: str
    duration: int  # seconds
    requester_id: int
    thumbnail: str = ""
    source: str = "youtube"  # youtube, spotify, etc.


@dataclass
class MusicPlayer:
    """Music player for a single guild."""
    guild_id: int
    queue: List[Track] = field(default_factory=list)
    current: Optional[Track] = None
    volume: int = 50  # 0-100
    loop: LoopMode = LoopMode.OFF
    is_paused: bool = False
    voice_client: Optional[VoiceClient] = None
    _player: Optional[discord.FFmpegPCMAudio] = None
    _task: Optional[asyncio.Task] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _channel_id: Optional[int] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_playing(self) -> bool:
        return self.current is not None and not self.is_paused

    @property
    def queue_length(self) -> int:
        return len(self.queue)

    async def join_voice_channel(self, guild: discord.Guild, channel: discord.VoiceChannel) -> bool:
        """Join a voice channel."""
        async with self._lock:
            try:
                if self.voice_client and self.voice_client.is_connected():
                    if self.voice_client.channel.id == channel.id:
                        return True
                    await self.voice_client.move_to(channel)
                    return True
                
                self.voice_client = await channel.connect()
                self._channel_id = channel.id
                logger.info(f"Joined voice channel {channel.name} in {guild.name}")
                return True
            except Exception as e:
                logger.error(f"Failed to join voice channel: {e}")
                return False

    async def leave_voice_channel(self):
        """Leave the current voice channel and cleanup."""
        async with self._lock:
            if self._task:
                self._task.cancel()
                self._task = None
            if self.voice_client:
                try:
                    await self.voice_client.disconnect()
                except Exception:
                    pass
                self.voice_client = None
            self.queue.clear()
            self.current = None
            self._channel_id = None
            self.is_paused = False

    async def add_to_queue(self, track: Track):
        """Add a track to the queue."""
        self.queue.append(track)

    async def get_next_track(self) -> Optional[Track]:
        """Get the next track from the queue, handling loop mode."""
        if not self.queue:
            if self.current and self.loop == LoopMode.TRACK:
                return self.current
            return None
        return self.queue.pop(0)

    async def play_next(self, guild: discord.Guild):
        """Play the next track in the queue."""
        if not self.voice_client or not self.voice_client.is_connected():
            return

        track = await self.get_next_track()
        if not track:
            asyncio.create_task(self._auto_leave(guild))
            return

        self.current = track
        self.is_paused = False

        try:
            source = await self._create_source(track.url)
            # Wrap in volume transformer
            source = discord.PCMVolumeTransformer(source)
            source.volume = self.volume / 100

            # Capture current event loop for the after callback
            # (called from FFmpeg thread, so create_task won't work)
            loop = asyncio.get_running_loop()

            self.voice_client.play(
                source,
                after=lambda e, _loop=loop, _guild=guild: _loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._on_track_end(e, _guild), loop=_loop)
                )
            )
        except Exception as e:
            logger.error(f"Failed to play track '{track.title}': {e}")
            self.current = None
            asyncio.create_task(self.play_next(guild))

    def _strip_playlist_params(self, url: str) -> str:
        """Strip playlist params (&list=, &index=) from URL to force single-video extraction."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        keep = {"v", "t", "feature", "hashtag", "sparams"}
        filtered = {k: v for k, v in params.items() if k in keep}
        new_query = urlencode(filtered, doseq=True)
        new_parsed = parsed._replace(query=new_query)
        return new_parsed.geturl()

    async def _create_source(self, url: str) -> discord.AudioSource:
        """Create FFmpeg audio source from URL (runs yt-dlp in threadpool)."""
        def _resolve_and_create():
            # Strip playlist params
            clean_url = self._strip_playlist_params(url)

            ydl_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "default_search": "auto",
                "extract_flat": False,
                "socket_timeout": 30,
            }

            # Resolve playlist URLs to a single video URL
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                if info is None:
                    raise ValueError("yt-dlp returned no info — video may be private or unavailable")

                if info.get("_type") == "playlist":
                    entries = info.get("entries", [])
                    if entries:
                        first_entry = entries[0]
                        clean_url = first_entry.get("webpage_url") or first_entry.get("url", clean_url)
                    # else: empty playlist, fall through with original url

            # Use use_ytdl=True so FFmpegPCMAudio internally resolves the YouTube URL
            # to an actual stream URL at playback time. This avoids:
            # 1. 403 Forbidden (signed URLs expire)
            # 2. "Invalid data found" (FFmpeg can't play YouTube URLs directly)
            ffmpeg_opts = {
                "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                "options": "-vn",
            }
            return discord.FFmpegPCMAudio(clean_url, **ffmpeg_opts, use_ytdl=True)

        # Run in threadpool so yt-dlp doesn't block the event loop
        return await asyncio.wait_for(
            asyncio.to_thread(_resolve_and_create),
            timeout=60.0
        )

    async def _on_track_end(self, error: Optional[Exception], guild: discord.Guild):
        """Called when the current track finishes."""
        if error:
            logger.error(f"Playback error: {error}")
        self.current = None
        await self.play_next(guild)

    async def _auto_leave(self, guild: discord.Guild):
        """Auto-leave voice channel when queue is empty."""
        await asyncio.sleep(30)  # Wait 30 seconds
        if not self.queue and not self.current:
            # Check if still connected and alone
            if self.voice_client and self.voice_client.is_connected():
                channel = self.voice_client.channel
                if channel and len(channel.members) == 1:
                    await self.leave_voice_channel()
                    logger.info(f"Left empty voice channel in {guild.name}")

    async def pause(self) -> bool:
        """Pause playback."""
        if not self.is_playing:
            return False
        self.voice_client.pause()
        self.is_paused = True
        return True

    async def resume(self) -> bool:
        """Resume playback."""
        if not self.is_paused:
            return False
        self.voice_client.resume()
        self.is_paused = False
        return True

    async def skip(self):
        """Skip current track."""
        if self.voice_client and self.voice_client.source:
            self.voice_client.stop()

    async def set_volume(self, volume: int):
        """Set volume (0-100)."""
        self.volume = max(0, min(100, volume))
        if self.voice_client and self.voice_client.source:
            try:
                self.voice_client.source.volume = self.volume / 100
            except Exception:
                pass  # Source might not support volume control

    async def shuffle(self):
        """Shuffle the queue."""
        import random
        random.shuffle(self.queue)

    async def remove_from_queue(self, position: int) -> bool:
        """Remove a track from the queue by position (1-based)."""
        if 0 <= position - 1 < len(self.queue):
            removed = self.queue.pop(position - 1)
            logger.info(f"Removed from queue: {removed.title}")
            return True
        return False

    def get_queue_display(self, user: discord.User) -> str:
        """Get a display string of the current queue."""
        lines = []
        if self.current:
            requester = f"<@{self.current.requester_id}>"
            lines.append(f"▶ Now Playing: **{self.current.title}** (Requested by {requester})")
        
        if self.queue:
            lines.append("\n📋 Queue:")
            for i, track in enumerate(self.queue[:10], 1):
                requester = f"<@{track.requester_id}>"
                duration = self._format_duration(track.duration)
                lines.append(f"{i}. **{track.title}** ({duration}) - {requester}")
            if len(self.queue) > 10:
                lines.append(f"... and {len(self.queue) - 10} more tracks")
        else:
            if not self.current:
                lines.append("Queue is empty. Use `/music play <url>` to add tracks!")
        
        loop_emoji = {"off": "❌", "track": "🔂", "queue": "🔁"}
        lines.append(f"\n🔊 Volume: {self.volume}% | Loop: {loop_emoji[self.loop.value]} | Status: {'⏸ Paused' if self.is_paused else '▶ Playing' if self.current else '⏹ Stopped'}")
        
        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format duration in seconds to mm:ss."""
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"


class MusicManager:
    """Manages MusicPlayer instances for all guilds."""

    def __init__(self):
        self._players: Dict[int, MusicPlayer] = {}
        self._lock = asyncio.Lock()

    def get_player(self, guild_id: int) -> MusicPlayer:
        """Get or create a MusicPlayer for a guild."""
        if guild_id not in self._players:
            self._players[guild_id] = MusicPlayer(guild_id=guild_id)
        return self._players[guild_id]

    async def cleanup(self):
        """Stop all players and cleanup."""
        for player in self._players.values():
            await player.leave_voice_channel()
        self._players.clear()