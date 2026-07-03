"""
Discord Server Manager Bot
Main entry point.
"""
import sys
import logging
from bot.client import BotClient
from bot.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("bot")


def main():
    config = Config()
    bot = BotClient(config)
    bot.run(config.BOT_TOKEN)


if __name__ == "__main__":
    main()
