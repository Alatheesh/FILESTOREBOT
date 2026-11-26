import asyncio
import logging
from pyrogram import Client, idle
from bot.config import Config
from bot.database import db
from bot.health import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("VaultBot")


async def main():
    logger.info("Initializing MongoDB indexes...")
    await db.init_indexes()

    logger.info(f"Starting health server on port {Config.PORT}...")
    health_runner = await start_health_server()

    app = Client(
        name="vault_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        plugins=dict(root="bot/plugins"),
        in_memory=True,
    )

    await app.start()
    me = await app.get_me()
    logger.info(f"Bot started successfully as @{me.username}")

    await idle()

    await app.stop()
    await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
