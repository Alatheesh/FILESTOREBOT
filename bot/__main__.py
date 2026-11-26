import asyncio
import logging
import aiohttp
from pyrogram import Client, idle
from bot.config import Config
from bot.database import db
from bot.webapp_server import start_webapp_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("VaultBot")


async def configure_menu_button():
    if not Config.WEBAPP_URL:
        return
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/setChatMenuButton"
    payload = {
        "menu_button": {
            "type": "web_app",
            "text": "My Vault",
            "web_app": {"url": f"{Config.WEBAPP_URL}/app"},
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                res = await resp.json()
                logger.info(f"Chat menu button configured: {res.get('ok')}")
    except Exception as e:
        logger.warning(f"Could not set menu button: {e}")


async def main():
    logger.info("Initializing MongoDB indexes...")
    await db.init_indexes()

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

    logger.info(f"Starting Mini App & Health server on port {Config.PORT}...")
    web_runner = await start_webapp_server(app)
    await configure_menu_button()

    await idle()

    await app.stop()
    await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
