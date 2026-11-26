import aiohttp
from urllib.parse import quote
from bot.config import Config


async def shorten_url(long_url: str) -> str:
    if not Config.SHORTENER_API or not Config.SHORTENER_DOMAIN:
        return long_url

    api_url = (
        f"https://{Config.SHORTENER_DOMAIN}/api"
        f"?api={Config.SHORTENER_API}&url={quote(long_url)}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                data = await resp.json()
                if data.get("status") == "success" and data.get("shortenedUrl"):
                    return data["shortenedUrl"]
    except Exception:
        pass
    return long_url
