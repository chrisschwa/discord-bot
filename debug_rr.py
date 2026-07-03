"""Debug script to check DB schema."""
import sqlite3
import os

os.chdir("/home/ubuntu/discord-bot")
conn = sqlite3.connect("data/bot.db")

# Check tables
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Tables: {[t[0] for t in tables]}")

# Check migrations
try:
    migrations = conn.execute("SELECT migration_id, applied_at FROM migrations ORDER BY migration_id").fetchall()
    print(f"Migrations: {[(m[0], m[1]) for m in migrations]}")
except:
    print("No migrations table")

# Check reaction_roles
try:
    rows = conn.execute("SELECT id, guild_id, channel_id, message_id, emoji, role_id FROM reaction_roles LIMIT 20").fetchall()
    print(f"Found {len(rows)} reaction roles:")
    for r in rows:
        print(f"  id={r[0]}, guild={r[1]}, ch={r[2]}, msg={r[3]}, emoji='{r[4]}', role={r[5]}")
except Exception as e:
    print(f"reaction_roles error: {e}")

conn.close()
