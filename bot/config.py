import os
from dotenv import load_dotenv

load_dotenv()


def _parse_int_list(raw: str) -> list[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]


class Config:
    API_ID: int = int(os.environ.get("API_ID", 0))
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

    WEBAPP_URL: str = os.environ.get("WEBAPP_URL", "").rstrip("/")

    DB_CHANNEL_ID: int = int(os.environ.get("DB_CHANNEL_ID", 0))
    OWNER_ID: int = int(os.environ.get("OWNER_ID", 0))
    ADMIN_IDS: list[int] = list(
        set([OWNER_ID] + _parse_int_list(os.environ.get("ADMIN_IDS", "")))
    )

    MONGO_URI: str = os.environ.get("MONGO_URI", "")
    DB_NAME: str = os.environ.get("DB_NAME", "telegram_vault_bot")

    FSUB_CHANNELS: list[int] = _parse_int_list(os.environ.get("FSUB_CHANNELS", ""))
    AUTO_DELETE_SECONDS: int = int(os.environ.get("AUTO_DELETE_SECONDS", 0))
    PROTECT_CONTENT: bool = os.environ.get("PROTECT_CONTENT", "False").lower() == "true"

    SHORTENER_API: str = os.environ.get("SHORTENER_API", "")
    SHORTENER_DOMAIN: str = os.environ.get("SHORTENER_DOMAIN", "")

    PORT: int = int(os.environ.get("PORT", 7860))
