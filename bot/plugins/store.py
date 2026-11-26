from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
    WebAppInfo,
)
from bot.config import Config
from bot.database import db
from bot.shortener import shorten_url

WIZARD_SESSIONS: dict[int, dict] = {}
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def _is_allowed_uploader(user_id: int) -> bool:
    if await db.is_banned(user_id):
        return False
    if user_id in Config.ADMIN_IDS:
        return True
    # Open to all users by default so everyone can build their own Mini App vault
    return bool(await db.get_setting("public_uploads", True))


def _extract_msg_id(token: str) -> int | None:
    token = token.strip().rstrip("/")
    if token.isdigit():
        return int(token)
    if "t.me/" in token:
        last_part = token.split("/")[-1]
        if last_part.isdigit():
            return int(last_part)
    return None


async def _make_share_reply(client: Client, slug: str, title: str) -> tuple[str, InlineKeyboardMarkup]:
    direct_url = f"https://t.me/{client.me.username}?start={slug}"
    final_url = await shorten_url(direct_url)
    text = (
        f"✅ **Stored in Your Vault!**\n\n"
        f"📌 **Title:** `{title}`\n"
        f"🔗 **Link:** {final_url}"
    )
    rows = [
        [
            InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={final_url}"),
            InlineKeyboardButton("📥 Get Now", url=direct_url),
        ]
    ]
    if Config.WEBAPP_URL:
        rows.append(
            [
                InlineKeyboardButton(
                    "📱 Manage in Mini App",
                    web_app=WebAppInfo(url=f"{Config.WEBAPP_URL}/app"),
                )
            ]
        )
    return text, InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("text") & filters.private)
async def store_text_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text("🔒 Uploads are currently restricted.")

    raw = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    if "|" not in raw:
        return await message.reply_text(
            "📝 **Usage:** `/text Note Title | Your full text content here`"
        )

    title, content = [part.strip() for part in raw.split("|", 1)]
    copied = await client.send_message(
        Config.DB_CHANNEL_ID, f"📝 **{title}**\n\n{content}"
    )
    slug = await db.save_item(
        item_type="text",
        message_ids=[copied.id],
        title=title[:120],
        created_by=user.id,
        owner_name=user.first_name or "",
        text_content=content,
        mime_type="text/plain",
    )
    reply_text, kb = await _make_share_reply(client, slug, title[:120])
    await message.reply_text(reply_text, reply_markup=kb, link_preview_options=NO_PREVIEW)


@Client.on_message(filters.command("wizard") & filters.private)
async def start_wizard(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text("🔒 Uploads are currently restricted.")

    title = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": []}
    await message.reply_text(
        f"🧙‍♂️ **Batch Wizard Started** (`{title[:120]}`)\n\n"
        "Send as many **files, videos, photos, audio, or text messages** as you want.\n"
        "• Send `/done` when finished to save into your Mini App Vault.\n"
        "• Send `/cancel` to abort."
    )


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_wizard(client: Client, message: Message):
    if WIZARD_SESSIONS.pop(message.from_user.id, None):
        await message.reply_text("❌ Wizard session cancelled.")


@Client.on_message(filters.command("done") & filters.private)
async def finish_wizard(client: Client, message: Message):
    user = message.from_user
    session = WIZARD_SESSIONS.pop(user.id, None)
    if not session or not session["msg_ids"]:
        return await message.reply_text("⚠️ No items collected in your wizard session.")

    slug = await db.save_item(
        item_type="batch",
        message_ids=session["msg_ids"],
        title=session["title"],
        created_by=user.id,
        owner_name=user.first_name or "",
    )
    reply_text, kb = await _make_share_reply(
        client, slug, f"{session['title']} ({len(session['msg_ids'])} items)"
    )
    await message.reply_text(reply_text, reply_markup=kb, link_preview_options=NO_PREVIEW)


@Client.on_message(filters.command("batch") & filters.private)
async def batch_range_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text("🔒 Uploads are currently restricted.")

    args = message.command[1:]
    start_id = _extract_msg_id(args[0]) if len(args) >= 1 else None
    end_id = _extract_msg_id(args[1]) if len(args) >= 2 else None

    if start_id is not None and end_id is not None and user.id in Config.ADMIN_IDS:
        title = " ".join(args[2:]).strip() if len(args) > 2 else f"Batch {start_id}-{end_id}"
        msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))

        slug = await db.save_item(
            item_type="batch",
            message_ids=msg_ids,
            title=title[:120],
            created_by=user.id,
            owner_name=user.first_name or "",
        )
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        return await message.reply_text(reply_text, reply_markup=kb, link_preview_options=NO_PREVIEW)

    title = " ".join(args).strip() if args else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": []}
    await message.reply_text(
        f"🧙‍♂️ **Interactive Batch Started** (`{title[:120]}`)\n\n"
        "Forward or send all the **files, videos, photos, or text messages** you want to bundle.\n"
        "• Type `/done` when finished to save into your vault.\n"
        "• Type `/cancel` to abort."
    )


@Client.on_message(
    filters.private
    & ~filters.command(
        [
            "start",
            "help",
            "text",
            "wizard",
            "done",
            "cancel",
            "batch",
            "search",
            "request",
            "stats",
            "broadcast",
            "ban",
            "unban",
            "autodel",
            "fsub",
            "publicmode",
        ]
    )
)
async def handle_incoming_storage(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return

    if user.id in WIZARD_SESSIONS:
        copied = await message.copy(Config.DB_CHANNEL_ID)
        WIZARD_SESSIONS[user.id]["msg_ids"].append(copied.id)
        count = len(WIZARD_SESSIONS[user.id]["msg_ids"])
        return await message.reply_text(
            f"➕ Added item **#{count}** to bundle. Send more or type `/done`."
        )

    if message.media:
        copied = await message.copy(Config.DB_CHANNEL_ID)
        media_obj = getattr(message, message.media.value, None)
        title = (
            getattr(media_obj, "file_name", None)
            or message.caption
            or f"{message.media.value.title()}_{copied.id}"
        )
        file_size = getattr(media_obj, "file_size", 0) or 0
        mime_type = getattr(media_obj, "mime_type", "") or ""

        slug = await db.save_item(
            item_type="single",
            message_ids=[copied.id],
            title=title[:120],
            created_by=user.id,
            owner_name=user.first_name or "",
            file_size=file_size,
            mime_type=mime_type,
        )
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        await message.reply_text(reply_text, reply_markup=kb, link_preview_options=NO_PREVIEW)
