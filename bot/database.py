"""
Database module - async SQLite wrapper using aiosqlite.
"""
import os
import aiosqlite
from typing import Optional, List, Tuple, Any
from datetime import datetime, timedelta

from bot.config import Config


class Database:
    """Async SQLite database manager for the Discord bot."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DATA_PATH
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Initialize the database connection and create tables."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def migrate_add_column(self, table: str, column: str, col_def: str):
        """Add a column to an existing table if it doesn't exist."""
        async with self._db.execute(f"PRAGMA table_info({table})") as cursor:
            columns = await cursor.fetchall()
            col_names = [c["name"] for c in columns]
            if column not in col_names:
                await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                await self._db.commit()

    async def _create_tables(self):
        """Create all required tables if they don't exist."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel_id INTEGER,
                welcome_message TEXT,
                welcome_dm TEXT,
                welcome_enabled BOOLEAN DEFAULT 1,
                leave_channel_id INTEGER,
                leave_message TEXT,
                log_channel_id INTEGER,
                voice_auto_enabled BOOLEAN DEFAULT 0,
                voice_auto_limit INTEGER DEFAULT 10,
                voice_auto_category_id INTEGER,
                voice_auto_suffix TEXT DEFAULT '_s-channel',
                automod_enabled BOOLEAN DEFAULT 1,
                ticket_category_id INTEGER,
                ticket_role_id INTEGER,
                music_channel_id INTEGER,
                leveling_enabled BOOLEAN DEFAULT 1,
                xp_per_message INTEGER DEFAULT 5,
                xp_cooldown INTEGER DEFAULT 30
            );

            CREATE TABLE IF NOT EXISTS reaction_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                UNIQUE(guild_id, message_id, emoji)
            );

            CREATE TABLE IF NOT EXISTS levels (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS level_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                UNIQUE(guild_id, level, role_id)
            );

            CREATE TABLE IF NOT EXISTS xp_cooldown (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                last_xp TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS muted_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                expires_at DATETIME,
                reason TEXT,
                moderator_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS automod_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                rule_type TEXT NOT NULL,
                action TEXT NOT NULL,
                pattern TEXT,
                enabled BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS bad_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                UNIQUE(guild_id, word)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                claimed_by INTEGER,
                status TEXT DEFAULT 'open',
                reason TEXT,
                transcript TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS message_history (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_reaction_roles_guild ON reaction_roles(guild_id);
            CREATE INDEX IF NOT EXISTS idx_warnings_guild ON warnings(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_automod_guild ON automod_rules(guild_id);
            CREATE INDEX IF NOT EXISTS idx_bad_words_guild ON bad_words(guild_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_guild ON tickets(guild_id);
            CREATE INDEX IF NOT EXISTS idx_message_history ON message_history(guild_id, user_id, timestamp);

            CREATE TABLE IF NOT EXISTS trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                started_by INTEGER NOT NULL,
                reason TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                duration_days INTEGER DEFAULT 14,
                status TEXT DEFAULT 'active',
                ended_at DATETIME,
                outcome_reason TEXT,
                UNIQUE(guild_id, user_id, status)
            );

            CREATE INDEX IF NOT EXISTS idx_trials_guild ON trials(guild_id, status);
        """)
        await self._db.commit()
        
        # Migrations - add missing columns to existing tables
        await self.migrate_add_column("server_settings", "music_channel_id", "INTEGER")
        await self.migrate_add_column("server_settings", "xp_per_message", "INTEGER DEFAULT 5")
        await self.migrate_add_column("server_settings", "xp_cooldown", "INTEGER DEFAULT 30")

    # ==================== Server Settings ====================

    async def get_server_settings(self, guild_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def set_server_settings(self, guild_id: int, **kwargs) -> dict:
        existing = await self.get_server_settings(guild_id)
        
        if existing:
            set_clauses = []
            params = []
            for key, value in kwargs.items():
                if value is not None:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)
            if set_clauses:
                params.append(guild_id)
                await self._db.execute(
                    f"UPDATE server_settings SET {', '.join(set_clauses)} WHERE guild_id = ?",
                    params
                )
                await self._db.commit()
        else:
            columns = list(kwargs.keys())
            cols_with_id = ["guild_id"] + columns
            params = [guild_id] + list(kwargs.values())
            placeholders = ", ".join(["?"] * len(cols_with_id))
            await self._db.execute(
                f"INSERT INTO server_settings ({', '.join(cols_with_id)}) VALUES ({placeholders})",
                params
            )
            await self._db.commit()

        return await self.get_server_settings(guild_id)

    # ==================== Reaction Roles ====================

    async def add_reaction_role(self, guild_id: int, channel_id: int, message_id: int, emoji: str, role_id: int) -> int:
        cursor = await self._db.execute(
            """INSERT OR REPLACE INTO reaction_roles 
               (guild_id, channel_id, message_id, emoji, role_id) 
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, channel_id, message_id, emoji, role_id)
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_reaction_roles(self, guild_id: int) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM reaction_roles WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_reaction_role(self, guild_id: int, message_id: int, emoji: str) -> Optional[dict]:
        async with self._db.execute(
            """SELECT * FROM reaction_roles 
               WHERE guild_id = ? AND message_id = ? AND emoji = ?""",
            (guild_id, message_id, emoji)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_reaction_role_emoji(self, reaction_id: int, new_emoji: str):
        await self._db.execute("UPDATE reaction_roles SET emoji = ? WHERE id = ?", (new_emoji, reaction_id))
        await self._db.commit()

    async def delete_reaction_role(self, reaction_id: int):
        await self._db.execute("DELETE FROM reaction_roles WHERE id = ?", (reaction_id,))
        await self._db.commit()

    async def update_reaction_role_message_id(self, reaction_id: int, channel_id: int, message_id: int):
        await self._db.execute(
            "UPDATE reaction_roles SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, reaction_id)
        )
        await self._db.commit()

    async def delete_reaction_roles_for_message(self, guild_id: int, message_id: int):
        await self._db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id)
        )
        await self._db.commit()

    # ==================== Leveling ====================

    async def get_user_level(self, guild_id: int, user_id: int) -> dict:
        async with self._db.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        
        await self._db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, level) VALUES (?, ?, 0, 0)",
            (guild_id, user_id)
        )
        await self._db.commit()
        return {"guild_id": guild_id, "user_id": user_id, "xp": 0, "level": 0}

    async def add_xp(self, guild_id: int, user_id: int, amount: int) -> dict:
        user = await self.get_user_level(guild_id, user_id)
        new_xp = user["xp"] + amount
        new_level = new_xp // 100
        
        await self._db.execute(
            "UPDATE levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
            (new_xp, new_level, guild_id, user_id)
        )
        await self._db.commit()
        
        return {
            "guild_id": guild_id, "user_id": user_id,
            "xp": new_xp, "level": new_level,
            "leveled_up": new_level > user["level"],
            "old_level": user["level"]
        }

    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_level_rewards(self, guild_id: int) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM level_rewards WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def add_level_reward(self, guild_id: int, level: int, role_id: int):
        await self._db.execute(
            "INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
            (guild_id, level, role_id)
        )
        await self._db.commit()

    async def can_get_xp(self, guild_id: int, user_id: int, channel_id: int, cooldown: int = 30) -> bool:
        async with self._db.execute(
            "SELECT last_xp FROM xp_cooldown WHERE guild_id = ? AND user_id = ? AND channel_id = ?",
            (guild_id, user_id, channel_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not row["last_xp"]:
                return True
            
            last_xp = datetime.fromisoformat(row["last_xp"])
            elapsed = (datetime.now() - last_xp).total_seconds()
            return elapsed >= cooldown

    async def set_xp_cooldown(self, guild_id: int, user_id: int, channel_id: int):
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT OR REPLACE INTO xp_cooldown (guild_id, user_id, channel_id, last_xp) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, channel_id, now)
        )
        await self._db.commit()

    # ==================== Moderation ====================

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        cursor = await self._db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason)
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_warnings(self, guild_id: int, user_id: int) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC",
            (guild_id, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mute_user(self, guild_id: int, user_id: int, role_id: int, expires_at: str, reason: str, moderator_id: int):
        await self._db.execute(
            """INSERT OR REPLACE INTO muted_users 
               (guild_id, user_id, role_id, expires_at, reason, moderator_id) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, role_id, expires_at, reason, moderator_id)
        )
        await self._db.commit()

    async def get_muted_user(self, guild_id: int, user_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM muted_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def unmute_user(self, guild_id: int, user_id: int):
        await self._db.execute(
            "DELETE FROM muted_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        await self._db.commit()

    # ==================== AutoMod ====================

    async def add_automod_rule(self, guild_id: int, rule_type: str, action: str, pattern: str = None) -> int:
        cursor = await self._db.execute(
            "INSERT INTO automod_rules (guild_id, rule_type, action, pattern) VALUES (?, ?, ?, ?)",
            (guild_id, rule_type, action, pattern)
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_automod_rules(self, guild_id: int) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM automod_rules WHERE guild_id = ? AND enabled = 1",
            (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def add_bad_word(self, guild_id: int, word: str):
        await self._db.execute(
            "INSERT OR IGNORE INTO bad_words (guild_id, word) VALUES (?, ?)",
            (guild_id, word.lower())
        )
        await self._db.commit()

    async def get_bad_words(self, guild_id: int) -> List[str]:
        async with self._db.execute(
            "SELECT word FROM bad_words WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row["word"] for row in rows]

    async def remove_bad_word(self, guild_id: int, word: str):
        await self._db.execute(
            "DELETE FROM bad_words WHERE guild_id = ? AND word = ?",
            (guild_id, word.lower())
        )
        await self._db.commit()

    async def log_message_sent(self, guild_id: int, user_id: int):
        await self._db.execute(
            "INSERT INTO message_history (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        await self._db.commit()

    async def get_recent_messages(self, guild_id: int, user_id: int, seconds: int = 5) -> int:
        since = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        async with self._db.execute(
            "SELECT COUNT(*) as count FROM message_history WHERE guild_id = ? AND user_id = ? AND timestamp > ?",
            (guild_id, user_id, since)
        ) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0

    async def clean_old_messages(self, guild_id: int, older_than_seconds: int = 60):
        since = (datetime.now() - timedelta(seconds=older_than_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        await self._db.execute(
            "DELETE FROM message_history WHERE guild_id = ? AND timestamp < ?",
            (guild_id, since)
        )
        await self._db.commit()

    async def check_message_cooldown(self, guild_id: int, user_id: int, seconds: int = 30) -> bool:
        since = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        async with self._db.execute(
            "SELECT COUNT(*) as count FROM message_history WHERE guild_id = ? AND user_id = ? AND timestamp > ?",
            (guild_id, user_id, since)
        ) as cursor:
            row = await cursor.fetchone()
            return (row["count"] if row else 0) == 0

    # ==================== Tickets ====================

    async def create_ticket(self, guild_id: int, channel_id: int, user_id: int, reason: str = None) -> int:
        cursor = await self._db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, user_id, reason)
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_ticket(self, guild_id: int, channel_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def close_ticket(self, guild_id: int, channel_id: int, transcript: str = None):
        now = datetime.now().isoformat()
        await self._db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ?, transcript = ? WHERE guild_id = ? AND channel_id = ?",
            (now, transcript, guild_id, channel_id)
        )
        await self._db.commit()

    async def claim_ticket(self, guild_id: int, channel_id: int, moderator_id: int):
        await self._db.execute(
            "UPDATE tickets SET claimed_by = ? WHERE guild_id = ? AND channel_id = ?",
            (moderator_id, guild_id, channel_id)
        )
        await self._db.commit()

    # ==================== Trials ====================

    async def create_trial(self, guild_id: int, user_id: int, started_by: int, reason: str, expires_at: datetime, duration_days: int):
        now = datetime.now().isoformat()
        await self._db.execute(
            """INSERT INTO trials (guild_id, user_id, started_by, reason, started_at, expires_at, duration_days, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
            (guild_id, user_id, started_by, reason, now, expires_at.isoformat(), duration_days)
        )
        await self._db.commit()

    async def get_trial(self, guild_id: int, user_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM trials WHERE guild_id = ? AND user_id = ? AND status = 'active'",
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_active_trials(self, guild_id: int) -> List[dict]:
        async with self._db.execute(
            "SELECT * FROM trials WHERE guild_id = ? AND status = 'active' ORDER BY started_at DESC",
            (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_expired_trials(self) -> List[dict]:
        now = datetime.now().isoformat()
        async with self._db.execute(
            "SELECT * FROM trials WHERE status = 'active' AND expires_at < ?",
            (now,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def end_trial(self, guild_id: int, user_id: int, outcome: str, reason: str):
        now = datetime.now().isoformat()
        await self._db.execute(
            "UPDATE trials SET status = ?, ended_at = ?, outcome_reason = ? WHERE guild_id = ? AND user_id = ? AND status = 'active'",
            (outcome, now, reason, guild_id, user_id)
        )
        await self._db.commit()

    async def get_trial_role_id(self, guild_id: int) -> Optional[int]:
        settings = await self.get_server_settings(guild_id)
        return settings.get("trial_role_id") if settings else None

    async def set_trial_role_id(self, guild_id: int, role_id: int):
        await self.set_server_settings(guild_id, trial_role_id=role_id)
