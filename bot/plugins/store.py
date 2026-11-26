from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import Config
from bot.database import db
from bot.shortener import shorten_url

WIZARD_SESSIONS: dict[int, dict] = {}


def _is_allowed_uploader(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS


async def _make_share_reply(client: Client, slug: str, title: str) -> tuple[str, InlineKeyboardMarkup]:
    direct_url = f"https://t.me/{client.me.username}?start={slug}"
    final_url = await shorten_url(direct_url)
    text = (
        f"✅ **Stored Successfully!**\n\n"
        f"📌 **Title:** `{title}`\n"
        f"🔗 **Link:** {final_url}"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={final_url}"),
                InlineKeyboardButton("📥 Open", url=direct_url),
            ]
        ]
    )
    return text, kb


@Client.on_message(filters.command("text") & filters.private)
async def store_text_cmd(client: Client, message: Message):
    if not _is_allowed_uploader(message.from_user.id):
        return await message.reply_text("🔒 Only admins can store new items.")

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
        title=title,
        created_by=message.from_user.id,
        text_content=content,
        mime_type="text/plain",
    )
    reply_text, kb = await _make_share_reply(client, slug, title)
    await message.reply_text(reply_text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_message(filters.command("wizard") & filters.private)
async def start_wizard(client: Client, message: Message):
    if not _is_allowed_uploader(message.from_user.id):
        return await message.reply_text("🔒 Only admins can use the upload wizard.")

    title = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else "Untitled Bundle"
    WIZARD_SESSIONS[message.from_user.id] = {"title": title, "msg_ids": []}
    await message.reply_text(
        f"🧙‍♂️ **Batch Wizard Started** (`{title}`)\n\n"
        "Send as many **files, videos, photos, audio, or text messages** as you want.\n"
        "• Send `/done` when finished to generate one combined link.\n"
        "• Send `/cancel` to abort."
    )


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_wizard(client: Client, message: Message):
    if WIZARD_SESSIONS.pop(message.from_user.id, None):
        await message.reply_text("❌ Wizard session cancelled.")


@Client.on_message(filters.command("done") & filters.private)
async def finish_wizard(client: Client, message: Message):
    session = WIZARD_SESSIONS.pop(message.from_user.id, None)
    if not session or not session["msg_ids"]:
        return await message.reply_text("⚠️ No items collected in your wizard session.")

    slug = await db.save_item(
        item_type="batch",
        message_ids=session["msg_ids"],
        title=session["title"],
        created_by=message.from_user.id,
    )
    reply_text, kb = await _make_share_reply(client, slug, f"{session['title']} ({len(session['msg_ids'])} items)")
    await message.reply_text(reply_text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_message(filters.command("batch") & filters.private)
async def batch_range_cmd(client: Client, message: Message):
    if not _is_allowed_uploader(message.from_user.id):
        return await message.reply_text("🔒 Only admins can create batches.")

    if len(message.command) < 3:
        return await message.reply_text(
            "📦 **Usage:** `/batch <start_msg_id> <end_msg_id> [Optional Title]`\n"
            "Example: `/batch 105 118 Season 1 Complete`"
        )

    start_id = int(message.command[1])
    end_id = int(message.command[2])
    title = " ".join(message.command[3:]) if len(message.command) > 3 else f"Batch {start_id}-{end_id}"
    msg_ids = list(range(min(start_id, end_id), max(start_id, end_id) + 1))

    slug = await db.save_item(
        item_type="batch",
        message_ids=msg_ids,
        title=title,
        created_by=message.from_user.id,
    )
    reply_text, kb = await _make_share_reply(client, slug, title)
    await message.reply_text(reply_text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_message(
    filters.private
    & ~filters.command(["start", "help", "text", "wizard", "done", "cancel", "batch", "search", "request", "stats", "broadcast", "ban", "unban", "autodel", "fsub"])
)
async def handle_incoming_storage(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_allowed_uploader(user_id):
        return

    if user_id in WIZARD_SESSIONS:
        copied = await message.copy(Config.DB_CHANNEL_ID)
        WIZARD_SESSIONS[user_id]["msg_ids"].append(copied.id)
        count = len(WIZARD_SESSIONS[user_id]["msg_ids"])
        return await message.reply_text(f"➕ Added item **#{count}** to bundle. Send more or type `/done`.")

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
            created_by=user_id,
            file_size=file_size,
            mime_type=mime_type,
        )
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        await message.reply_text(reply_text, reply_markup=kb, disable_web_page_preview=True)
