import html
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    LinkPreviewOptions,
)
from bot.config import Config
from bot.database import db
from bot.shortener import shorten_url
from bot.delivery import deliver_item, check_item_availability, destroy_expired_item
from bot.plugins.start import PENDING_PIN_USERS

WIZARD_SESSIONS: dict[int, dict] = {}
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def _is_allowed_uploader(user_id: int) -> bool:
    if await db.is_banned(user_id):
        return False
    if user_id in Config.ADMIN_IDS:
        return True
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


def _describe_message(message: Message, fallback_index: int) -> dict:
    if message.media:
        media_obj = getattr(message, message.media.value, None)
        label = (
            getattr(media_obj, "file_name", None)
            or message.caption
            or f"{message.media.value.title()} #{fallback_index}"
        )
        return {"title": label[:90], "type": message.media.value}
    if message.text:
        snippet = message.text.strip().splitlines()[0][:60]
        return {"title": f"Text: {snippet}", "type": "text"}
    return {"title": f"Item #{fallback_index}", "type": "item"}


async def _make_share_reply(client: Client, slug: str, title: str) -> tuple[str, InlineKeyboardMarkup]:
    direct_url = f"https://t.me/{client.me.username}?start={slug}"
    final_url = await shorten_url(direct_url)
    safe_title = html.escape(title)
    text = (
        f"✅ <b>Stored in Your Vault!</b>\n\n"
        f"📌 <b>Title:</b> <code>{safe_title}</code>\n"
        f"🔗 <b>Link:</b> {final_url}"
        f"{Config.CREDITS_HTML}"
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
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    raw = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    if "|" not in raw:
        return await message.reply_text(
            f"📝 <b>Usage:</b> <code>/text Note Title | Your full text content here</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title, content = [part.strip() for part in raw.split("|", 1)]
    copied = await client.send_message(
        Config.DB_CHANNEL_ID,
        f"📝 <b>{html.escape(title)}</b>\n\n{html.escape(content)}",
        parse_mode=ParseMode.HTML,
    )
    slug = await db.save_item(
        item_type="text",
        message_ids=[copied.id],
        title=title[:120],
        created_by=user.id,
        owner_name=user.first_name or "",
        text_content=content,
        mime_type="text/plain",
        sub_items=[{"msg_id": copied.id, "title": title[:90], "type": "text"}],
    )
    reply_text, kb = await _make_share_reply(client, slug, title[:120])
    await message.reply_text(
        reply_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("wizard") & filters.private)
async def start_wizard(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": [], "sub_items": []}
    await message.reply_text(
        f"🧙‍♂️ <b>Batch Wizard Started</b> (<code>{html.escape(title[:120])}</code>)\n\n"
        "Send as many <b>files, videos, photos, audio, or text messages</b> as you want.\n"
        "• Send <code>/done</code> when finished to save into your Mini App Vault.\n"
        f"• Send <code>/cancel</code> to abort.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_wizard(client: Client, message: Message):
    if WIZARD_SESSIONS.pop(message.from_user.id, None):
        await message.reply_text(
            f"❌ Wizard session cancelled.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )


@Client.on_message(filters.command("done") & filters.private)
async def finish_wizard(client: Client, message: Message):
    user = message.from_user
    session = WIZARD_SESSIONS.pop(user.id, None)
    if not session or not session["msg_ids"]:
        return await message.reply_text(
            f"⚠️ No items collected in your wizard session.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    slug = await db.save_item(
        item_type="batch",
        message_ids=session["msg_ids"],
        title=session["title"],
        created_by=user.id,
        owner_name=user.first_name or "",
        sub_items=session["sub_items"],
    )
    reply_text, kb = await _make_share_reply(
        client, slug, f"{session['title']} ({len(session['msg_ids'])} items)"
    )
    await message.reply_text(
        reply_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("batch") & filters.private)
async def batch_range_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    args = message.command[1:]
    start_id = _extract_msg_id(args[0]) if len(args) >= 1 else None
    end_id = _extract_msg_id(args[1]) if len(args) >= 2 else None

    if start_id is not None and end_id is not None and user.id in Config.ADMIN_IDS:
        title = " ".join(args[2:]).strip() if len(args) > 2 else f"Batch {start_id}-{end_id}"
        msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))
        sub_items = [
            {"msg_id": mid, "title": f"Part #{idx + 1}", "type": "media"}
            for idx, mid in enumerate(msg_ids)
        ]

        slug = await db.save_item(
            item_type="batch",
            message_ids=msg_ids,
            title=title[:120],
            created_by=user.id,
            owner_name=user.first_name or "",
            sub_items=sub_items,
        )
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        return await message.reply_text(
            reply_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title = " ".join(args).strip() if args else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": [], "sub_items": []}
    await message.reply_text(
        f"🧙‍♂️ <b>Interactive Batch Started</b> (<code>{html.escape(title[:120])}</code>)\n\n"
        "Forward or send all the <b>files, videos, photos, or text messages</b> you want to bundle.\n"
        "• Type <code>/done</code> when finished to save into your vault.\n"
        f"• Type <code>/cancel</code> to abort.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(
    filters.private
    & ~filters.command(
        [
            "start",
            "help",
            "about",
            "text",
            "wizard",
            "done",
            "cancel",
            "batch",
            "search",
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

    if user.id in PENDING_PIN_USERS and message.text:
        entered_pin = message.text.strip()
        slug = PENDING_PIN_USERS.get(user.id)
        item = await db.get_item(slug) if slug else None
        if not item:
            PENDING_PIN_USERS.pop(user.id, None)
            return await message.reply_text(
                f"❌ This link is no longer available.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        available, _ = check_item_availability(item, user.id)
        if not available:
            PENDING_PIN_USERS.pop(user.id, None)
            await destroy_expired_item(client, item)
            return await message.reply_text(
                f"⌛ This link has expired or reached its view limit.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        if entered_pin == item.get("pin_code"):
            PENDING_PIN_USERS.pop(user.id, None)
            await message.reply_text(
                f"🔓 <b>PIN Verified!</b> Delivering your item...{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )
            return await deliver_item(client, message.chat.id, item)
        else:
            return await message.reply_text(
                f"❌ <b>Incorrect PIN.</b> Try again or send <code>/start</code> to cancel.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

    if not await _is_allowed_uploader(user.id):
        return

    if user.id in WIZARD_SESSIONS:
        copied = await message.copy(Config.DB_CHANNEL_ID)
        idx = len(WIZARD_SESSIONS[user.id]["msg_ids"]) + 1
        meta = _describe_message(message, idx)
        WIZARD_SESSIONS[user.id]["msg_ids"].append(copied.id)
        WIZARD_SESSIONS[user.id]["sub_items"].append(
            {"msg_id": copied.id, "title": meta["title"], "type": meta["type"]}
        )
        return await message.reply_text(
            f"➕ Added <b>{html.escape(meta['title'])}</b> (#{idx}) to bundle. Send more or type <code>/done</code>.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
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
            sub_items=[{"msg_id": copied.id, "title": title[:90], "type": message.media.value}],
        )
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        await message.reply_text(
            reply_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
