import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qsl
import aiohttp
from aiohttp import web
from pyrogram import Client
from bot.config import Config
from bot.database import db
from bot.delivery import deliver_item

STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp"


def verify_telegram_init_data(init_data: str) -> dict | None:
    if not init_data or not Config.BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(
            b"WebAppData", Config.BOT_TOKEN.encode("utf-8"), hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        user_raw = parsed.get("user")
        return json.loads(user_raw) if user_raw else None
    except Exception:
        return None


def _auth_user(request: web.Request) -> dict | None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    return verify_telegram_init_data(init_data)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "telegram-vault-bot-v2"})


async def handle_app_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def api_list_items(request: web.Request) -> web.Response:
    user = _auth_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized Telegram session"}, status=401)

    user_id = int(user["id"])
    q = request.query.get("q", "").strip()
    item_type = request.query.get("type", "all").strip()
    sort_by = request.query.get("sort", "newest").strip()

    items = await db.get_user_items(
        user_id=user_id, query=q, item_type=item_type, sort_by=sort_by
    )
    bot_username = request.app["bot"].me.username
    return web.json_response(
        {
            "user": {
                "id": user_id,
                "first_name": user.get("first_name", ""),
                "username": user.get("username", ""),
            },
            "bot_username": bot_username,
            "items": items,
        }
    )


async def api_update_item(request: web.Request) -> web.Response:
    user = _auth_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    slug = request.match_info["slug"]
    user_id = int(user["id"])
    body = await request.json()

    updated = await db.update_user_item(
        slug=slug,
        user_id=user_id,
        title=body.get("title"),
        text_content=body.get("text_content"),
    )
    if not updated:
        return web.json_response(
            {"error": "Item not found or you do not own this item"}, status=403
        )

    # Also update text message inside DB_CHANNEL_ID if it is a text note
    if updated["type"] == "text" and updated.get("message_ids"):
        bot: Client = request.app["bot"]
        try:
            await bot.edit_message_text(
                chat_id=Config.DB_CHANNEL_ID,
                message_id=updated["message_ids"][0],
                text=f"📝 **{updated['title']}**\n\n{updated.get('text_content', '')}",
            )
        except Exception:
            pass

    return web.json_response({"ok": True, "item": updated})


async def api_delete_item(request: web.Request) -> web.Response:
    user = _auth_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    slug = request.match_info["slug"]
    user_id = int(user["id"])

    # Deletes from MongoDB ONLY if created_by == user_id
    deleted = await db.delete_user_item(slug=slug, user_id=user_id)
    if not deleted:
        return web.json_response(
            {"error": "Item not found or belongs to another user"}, status=403
        )

    # Delete ONLY this item's stored messages from the private DB channel
    bot: Client = request.app["bot"]
    msg_ids = deleted.get("message_ids", [])
    if msg_ids:
        try:
            await bot.delete_messages(chat_id=Config.DB_CHANNEL_ID, message_ids=msg_ids)
        except Exception:
            pass

    return web.json_response({"ok": True, "deleted_slug": slug})


async def api_deliver_item(request: web.Request) -> web.Response:
    user = _auth_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    slug = request.match_info["slug"]
    user_id = int(user["id"])

    if await db.is_banned(user_id):
        return web.json_response({"error": "You are banned"}, status=403)

    item = await db.get_item(slug)
    if not item:
        return web.json_response({"error": "Item not found"}, status=404)

    bot: Client = request.app["bot"]
    await deliver_item(bot, user_id, item)
    return web.json_response({"ok": True, "message": "Sent to your Telegram chat!"})


async def api_prepare_share(request: web.Request) -> web.Response:
    user = _auth_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    slug = request.match_info["slug"]
    user_id = int(user["id"])
    item = await db.get_item(slug)
    if not item:
        return web.json_response({"error": "Item not found"}, status=404)

    bot_username = request.app["bot"].me.username
    deep_link = f"https://t.me/{bot_username}?start={slug}"

    payload = {
        "user_id": user_id,
        "result": {
            "type": "article",
            "id": slug,
            "title": item["title"],
            "description": f"Vault {item['type'].upper()} • Tap to open in @{bot_username}",
            "input_message_content": {
                "message_text": f"📦 <b>{item['title']}</b>\n\n🔗 <a href='{deep_link}'>Open in Vault Bot</a>",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "📥 Get File / Text", "url": deep_link}]
                ]
            },
        },
        "allow_user_chats": True,
        "allow_bot_chats": True,
        "allow_group_chats": True,
        "allow_channel_chats": True,
    }

    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/savePreparedInlineMessage"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=10) as resp:
            data = await resp.json()
            if data.get("ok") and data.get("result", {}).get("id"):
                return web.json_response({"ok": True, "prepared_id": data["result"]["id"]})
            return web.json_response(
                {"error": data.get("description", "Failed to prepare message")},
                status=400,
            )


async def start_webapp_server(bot: Client) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot

    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/app", handle_app_index)
    app.router.add_static("/static", STATIC_DIR)

    app.router.add_get("/api/items", api_list_items)
    app.router.add_patch("/api/items/{slug}", api_update_item)
    app.router.add_delete("/api/items/{slug}", api_delete_item)
    app.router.add_post("/api/deliver/{slug}", api_deliver_item)
    app.router.add_post("/api/prepare-share/{slug}", api_prepare_share)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    return runner
