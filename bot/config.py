"""
Configuration management using python-dotenv.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration loaded from environment variables."""

    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
    PREFIX: str = os.getenv("PREFIX", "!")
    DATA_PATH: str = os.getenv("DATA_PATH", "./data/bot.db")

    # Intents are set in client.py but documented here
    # All intents are enabled for full functionality

    # Validate required config
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is not set. Create a .env file with your bot token."
        )