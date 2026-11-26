import html
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    WebAppInfo,
    LinkPreviewOptions,
)
from pyrogram.errors import UserNotParticipant
from bot.config import Config
from bot.database import db
from bot.delivery import deliver_item, check_item_availability, destroy_expired_item

PENDING_PIN_USERS: dict[int, str] = {}
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def check_fsub(client: Client, user_id: int) -> list[dict]:
    if user_id in Config.ADMIN_IDS:
        return []
    channels = await db.get_setting("fsub_channels", Config.FSUB_CHANNELS)
    missing = []
    for ch_id in channels:
        try:
            member = await client.get_chat_member(ch_id, user_id)
            if member.status.name in ("BANNED", "LEFT"):
                raise UserNotParticipant
        except UserNotParticipant:
            chat = await client.get_chat(ch_id)
            invite = chat.invite_link or await client.export_chat_invite_link(ch_id)
            missing.append({"title": chat.title, "url": invite})
        except Exception:
            continue
    return missing


def _home_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if Config.WEBAPP_URL:
        rows.append(
            [
                InlineKeyboardButton(
                    "📱 Open My Vault Mini App",
                    web_app=WebAppInfo(url=f"{Config.WEBAPP_URL}/app"),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("🔍 Search Vault", switch_inline_query_current_chat=""),
            InlineKeyboardButton("📖 Help", callback_data="help_menu"),
            InlineKeyboardButton("ℹ️ About", callback_data="about_menu"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _welcome_text(first_name: str) -> str:
    safe_name = html.escape(first_name or "Friend")
    return (
        f"👋 <b>Welcome, {safe_name}!</b>\n\n"
        "Your personal <b>Telegram File &amp; Text Vault</b> with an integrated <b>Mini App Manager</b>.\n\n"
        "• Send any <b>file, video, photo, or audio</b> → Saved to your vault\n"
        "• <code>/text Title | Content</code> → Save a formatted text note\n"
        "• <code>/wizard Title</code> → Bundle multiple files &amp; texts into one link\n"
        "• Tap <b>Open My Vault Mini App</b> below to sort, rename, set PIN/expiring links, inspect batches, generate QR codes, or delete your items!"
        f"{Config.CREDITS_HTML}"
    )


def _help_text() -> str:
    return (
        "📖 <b>Vault Bot — Command Guide</b>\n\n"
        "<b>👤 Personal Vault Commands (All Users)</b>\n"
        "• <b>Send any Media/File</b> → Instant link in your vault\n"
        "• <code>/text Title | Content</code> → Store a text note\n"
        "• <code>/wizard Title</code> → Multi-file &amp; text bundler\n"
        "• <code>/done</code> • <code>/cancel</code> → Finish or abort active wizard\n"
        "• <code>/batch Title</code> → Interactive bundle collector\n"
        "• <code>/search keyword</code> → Search your saved items\n"
        "• <code>/about</code> → Bot info &amp; credits\n\n"
        "<b>📱 Mini App Features</b>\n"
        "• ⚙️ <b>Link Rules:</b> 24h auto-expire, 4-digit PIN lock, or 1-time self-destruct\n"
        "• 📂 <b>Batch Inspector:</b> Reorder, remove, or fetch single items from a batch\n"
        "• 📱 <b>QR Codes &amp; Share:</b> Instant QR code &amp; native Telegram chat sharing\n\n"
        "<b>🛡️ Admin Commands</b>\n"
        "• <code>/stats</code> • <code>/broadcast</code> • <code>/publicmode on|off</code>\n"
        "• <code>/ban id</code> • <code>/unban id</code> • <code>/autodel sec</code> • <code>/fsub ids</code>"
        f"{Config.CREDITS_HTML}"
    )


def _about_text(bot_name: str, bot_username: str) -> str:
    safe_bot = html.escape(bot_name or "Vault Bot")
    return (
        "ℹ️ <b>About This Bot</b>\n\n"
        f"• <b>Name :</b> {safe_bot} (@{bot_username})\n"
        '• <b>Powered by :</b> <a href="https://t.me/llathu63035">NTM</a>\n'
        '• <b>Build by :</b> <a href="https://t.me/TG_LATHEESH"><b>LATHEESH</b></a>\n'
        "• <b>Server :</b> <code>secret</code> 🔒\n\n"
        "✨ <i>Enjoy fast, private, zero-load cloud storage!</i>"
        f"{Config.CREDITS_HTML}"
    )


@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    PENDING_PIN_USERS.pop(user.id, None)

    if await db.is_banned(user.id):
        return await message.reply_text(
            f"🚫 You are banned from using this bot.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    payload = message.command[1] if len(message.command) > 1 else None

    if payload:
        missing = await check_fsub(client, user.id)
        if missing:
            buttons = [
                [InlineKeyboardButton(f"Join {ch['title']}", url=ch["url"])]
                for ch in missing
            ]
            buttons.append(
                [InlineKeyboardButton("✅ Try Again", url=f"https://t.me/{client.me.username}?start={payload}")]
            )
            return await message.reply_text(
                "⚠️ <b>Join Required</b>\n\nPlease join our channel(s) below first, then click <b>Try Again</b> to receive your file/text."
                f"{Config.CREDITS_HTML}",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        item = await db.get_item(payload)
        if not item:
            return await message.reply_text(
                f"❌ Invalid or deleted link.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        available, reason = check_item_availability(item, user.id)
        if not available:
            await destroy_expired_item(client, item)
            if reason == "expired":
                return await message.reply_text(
                    f"⌛ <b>Link Expired:</b> This link has passed its expiration window and was automatically removed.{Config.CREDITS_HTML}",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                )
            return await message.reply_text(
                f"💥 <b>Self-Destructed:</b> This link reached its maximum view/download limit.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        pin_code = item.get("pin_code", "")
        is_owner = int(item.get("created_by", 0)) == int(user.id)
        if pin_code and not is_owner:
            PENDING_PIN_USERS[user.id] = payload
            return await message.reply_text(
                f"🔐 <b>PIN Protected Link</b>\n\n"
                f"📌 <b>Title:</b> <code>{html.escape(item['title'])}</code>\n"
                f"Please reply with the <b>4-digit PIN</b> to unlock and receive this item:{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        return await deliver_item(client, message.chat.id, item)

    await message.reply_text(
        _welcome_text(user.first_name or ""),
        reply_markup=_home_keyboard(),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    await message.reply_text(
        _help_text(),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Home", callback_data="back_start")]]
        ),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("about") & filters.private)
async def about_cmd(client: Client, message: Message):
    await message.reply_text(
        _about_text(client.me.first_name, client.me.username),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Home", callback_data="back_start")]]
        ),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_callback_query(filters.regex("^help_menu$"))
async def help_cb(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        _help_text(),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("ℹ️ About", callback_data="about_menu"),
                    InlineKeyboardButton("⬅️ Back", callback_data="back_start"),
                ]
            ]
        ),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_callback_query(filters.regex("^about_menu$"))
async def about_cb(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        _about_text(client.me.first_name, client.me.username),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📖 Help", callback_data="help_menu"),
                    InlineKeyboardButton("⬅️ Back", callback_data="back_start"),
                ]
            ]
        ),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_callback_query(filters.regex("^back_start$"))
async def back_cb(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        _welcome_text(query.from_user.first_name or ""),
        reply_markup=_home_keyboard(),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )
