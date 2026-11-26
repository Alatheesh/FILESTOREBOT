import os
from dotenv import load_dotenv

load_dotenv()


def _parse_int_list(raw: str) -> list[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]


def _parse_uri_list() -> list[str]:
    uris: list[str] = []
    raw_multi = os.environ.get("MONGO_URIS", "")
    if raw_multi:
        uris.extend([u.strip() for u in raw_multi.split(",") if u.strip()])
    single = os.environ.get("MONGO_URI", "").strip()
    if single and single not in uris:
        uris.insert(0, single)
    # Also support numbered secrets: MONGO_URI_1, MONGO_URI_2, ... up to 20
    for idx in range(1, 21):
        val = os.environ.get(f"MONGO_URI_{idx}", "").strip()
        if val and val not in uris:
            uris.append(val)
    return uris


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

    # Multi-DB Failover Pool
    MONGO_URIS: list[str] = _parse_uri_list()
    MONGO_URI: str = MONGO_URIS[0] if MONGO_URIS else ""
    DB_NAME: str = os.environ.get("DB_NAME", "telegram_vault_bot")
    DB_MAX_SIZE_MB: float = float(os.environ.get("DB_MAX_SIZE_MB", 460.0))

    FSUB_CHANNELS: list[int] = _parse_int_list(os.environ.get("FSUB_CHANNELS", ""))
    AUTO_DELETE_SECONDS: int = int(os.environ.get("AUTO_DELETE_SECONDS", 0))
    PROTECT_CONTENT: bool = os.environ.get("PROTECT_CONTENT", "False").lower() == "true"

    SHORTENER_API: str = os.environ.get("SHORTENER_API", "")
    SHORTENER_DOMAIN: str = os.environ.get("SHORTENER_DOMAIN", "")

    PORT: int = int(os.environ.get("PORT", 7860))

    # Global HTML Credits Footer
    CREDITS_HTML: str = (
        '\n\n━━━━━━━━━━━━━━━━━━━━\n'
        'BY [-_-] <a href="https://t.me/llathu63035">NTM</a> • '
        'By <a href="https://t.me/TG_LATHEESH"><b>LATHEESH</b></a>'
    )
