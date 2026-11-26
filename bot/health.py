from aiohttp import web
from bot.config import Config


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "telegram-vault-bot"})


async def start_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    return runner
