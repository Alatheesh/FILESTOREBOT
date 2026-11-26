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


def _privacy_url() -> str:
    return f"{Config.WEBAPP_URL}/privacy" if Config.WEBAPP_URL else "https://telegram.org/privacy-tpa"


def consent_prompt_payload(first_name: str, pending_slug: str = "") -> tuple[str, InlineKeyboardMarkup]:
    safe_name = html.escape(first_name or "Friend")
    policy_link = _privacy_url()
    text = (
        f"👋 <b>Hi {safe_name}!</b>\n\n"
        "Before using this <b>File Store Bot</b>, please read and accept our <b>Privacy Policy &amp; Disclaimer</b>:\n\n"
        "• <b>Not Responsible:</b> We only provide automated storage &amp; link sharing. Users are 100% responsible for the files they upload or share.\n"
        "• <b>No Illegal / Pirated Content:</b> Uploading copyrighted media, malware, or illegal content is strictly forbidden and results in an instant ban.\n"
        "• <b>Your Privacy:</b> Only your Telegram User ID and file references are stored, and you can delete your files permanently anytime in the Mini App."
        f"{Config.CREDITS_HTML}"
    )
    cb_data = f"accept_terms:{pending_slug}" if pending_slug else "accept_terms"
    rows = []
    if Config.WEBAPP_URL:
        rows.append([InlineKeyboardButton("🔒 Read Full Privacy Policy", url=policy_link)])
    rows.append([InlineKeyboardButton("✅ I Accept & Continue", callback_data=cb_data)])
    return text, InlineKeyboardMarkup(rows)


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
        f"👋 <b>Hi {safe_name}!</b>\n\n"
        "This is a <b>File Store Bot</b>. Forward or send any file, media, or text to store it permanently, "
        "and share it with anyone just by sharing your generated link.\n\n"
        "📱 Open <b>My Vault Mini App</b> below to manage, sort, or delete your stored files anytime."
        f"{Config.CREDITS_HTML}"
    )


def _help_text() -> str:
    return (
        "📖 <b>Vault Bot — Command Guide</b>\n\n"
        "<b>👤 Personal Vault Commands (All Users)</b>\n"
        "• <b>Send any Media/File</b> → Instant link in your vault\n"
        "• <code>/text Title | Content</code> → Store a text note\n"
        "• <code>/wizard Title</code> → Interactive file &amp; text bundler\n"
        "• <code>/done</code> • <code>/cancel</code> → Finish or abort active session\n"
        "• <code>/search keyword</code> → Search your saved items\n"
        "• <code>/about</code> → Bot info, credits &amp; privacy policy\n\n"
        "<b>📦 Dual-Mode Batching (Available for Everyone!)</b>\n"
        "1️⃣ <b>Interactive Mode:</b> Send <code>/batch My Bundle</code>, forward or send your files/texts one by one, then send <code>/done</code>.\n"
        "2️⃣ <b>Channel Link Mode:</b> Send <code>/batch &lt;first_post_link&gt; &lt;last_post_link&gt; [Title]</code>\n"
        "   • <b>Public Channel:</b> Works immediately with any public <code>t.me/channel/12</code> links!\n"
        "   • <b>Private Channel:</b> Add this bot as an <b>Admin</b> to your private channel first, then pass its <code>t.me/c/...</code> post links.\n\n"
        "<b>📱 Mini App Features</b>\n"
        "• ⚙️ <b>Link Rules:</b> 24h auto-expire, 4-digit PIN lock, or 1-time self-destruct\n"
        "• 📂 <b>Batch Inspector:</b> Reorder, remove, or fetch single items from a batch\n"
        "• 📱 <b>QR Codes &amp; Share:</b> Instant QR code &amp; native Telegram chat sharing\n\n"
        "<b>🛡️ Admin Commands</b>\n"
        "• <code>/stats</code> • <code>/dbstats</code> • <code>/adddb</code> • <code>/switchdb</code> • <code>/dblimit</code>\n"
        "• <code>/broadcast</code> • <code>/publicmode</code> • <code>/ban</code> • <code>/unban</code> • <code>/autodel</code> • <code>/fsub</code>"
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


def _about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔒 Privacy Policy & Disclaimer", callback_data="privacy_menu")],
            [
                InlineKeyboardButton("📖 Help", callback_data="help_menu"),
                InlineKeyboardButton("⬅️ Back", callback_data="back_start"),
            ],
        ]
    )


def _privacy_text() -> str:
    return (
        "🔒 <b>Privacy Policy &amp; Disclaimer</b>\n\n"
        "⚠️ <b>Disclaimer (Zero Liability):</b>\n"
        "We are <b>not responsible</b> for any files, media, or links uploaded or shared by users. "
        "Each user is solely responsible for their own content.\n\n"
        "• <b>Anti-Piracy &amp; Safety:</b> Copyrighted/pirated files, malware, and illegal content are strictly forbidden and will be deleted with an immediate ban.\n"
        "• <b>Your Privacy:</b> Only your Telegram User ID and file references are stored to keep your vault private. Nothing is sold or shared.\n"
        "• <b>Instant Control:</b> You can permanently delete any of your files anytime inside the Mini App."
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

    if not await db.has_accepted_terms(user.id):
        text, kb = consent_prompt_payload(user.first_name or "", pending_slug=payload or "")
        return await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

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


@Client.on_callback_query(filters.regex("^accept_terms"))
async def accept_terms_cb(client: Client, query: CallbackQuery):
    user = query.from_user
    await db.accept_terms(user.id)
    await query.answer("✅ Terms & Privacy Policy accepted!")

    parts = query.data.split(":", 1)
    pending_slug = parts[1].strip() if len(parts) > 1 else ""

    if pending_slug:
        await query.message.edit_text(
            f"✅ <b>Accepted!</b> Fetching your requested file...{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
        item = await db.get_item(pending_slug)
        if not item:
            return await query.message.reply_text(
                f"❌ Invalid or deleted link.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )
        return await deliver_item(client, query.message.chat.id, item)

    await query.message.edit_text(
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
        reply_markup=_about_keyboard(),
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
        reply_markup=_about_keyboard(),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_callback_query(filters.regex("^privacy_menu$"))
async def privacy_cb(client: Client, query: CallbackQuery):
    rows = []
    if Config.WEBAPP_URL:
        rows.append([InlineKeyboardButton("🌐 Open Full Policy Page", url=_privacy_url())])
    rows.append(
        [
            InlineKeyboardButton("⬅️ Back to About", callback_data="about_menu"),
            InlineKeyboardButton("🏠 Home", callback_data="back_start"),
        ]
    )
    await query.message.edit_text(
        _privacy_text(),
        reply_markup=InlineKeyboardMarkup(rows),
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
