from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    WebAppInfo,
)
from pyrogram.errors import UserNotParticipant
from bot.config import Config
from bot.database import db
from bot.delivery import deliver_item


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
            InlineKeyboardButton("🔍 Search My Vault", switch_inline_query_current_chat=""),
            InlineKeyboardButton("ℹ️ Help", callback_data="help_menu"),
        ]
    )
    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")

    if await db.is_banned(user.id):
        return await message.reply_text("🚫 You are banned from using this bot.")

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
                "⚠️ **Join Required**\n\nPlease join our channel(s) below first, then click **Try Again** to get your file/text.",
                reply_markup=InlineKeyboardMarkup(buttons),
            )

        item = await db.get_item(payload)
        if not item:
            return await message.reply_text("❌ Invalid or deleted link.")
        return await deliver_item(client, message.chat.id, item)

    await message.reply_text(
        f"👋 **Welcome, {user.first_name}!**\n\n"
        "This is your personal **Telegram File & Text Vault** with a built-in **Mini App Manager**.\n\n"
        "• Send any file, video, photo, or audio → Saved under your account\n"
        "• `/text Title | Content` → Store a text note\n"
        "• `/wizard Title` → Bundle multiple files & texts into one link\n"
        "• Tap **Open My Vault Mini App** below to sort, rename, edit, get, share, or delete **your** stored items anytime!",
        reply_markup=_home_keyboard(),
    )


@Client.on_callback_query(filters.regex("^help_menu$"))
async def help_cb(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        "📖 **Available Commands**\n\n"
        "**Personal Vault Commands (All Users):**\n"
        "• Send any file/photo/video/audio → Instant link in your vault\n"
        "• `/text <title> | <content>` → Store a text note\n"
        "• `/wizard <title>` → Step-by-step multi-file & text bundler\n"
        "• `/batch <start_id> <end_id> [Title]` → Bundle channel ID range\n"
        "• `/search <query>` → Search your saved files & texts\n"
        "• `/request <details>` → Send a request to admins\n\n"
        "**Admin Commands:**\n"
        "• `/stats` • `/broadcast` • `/ban` • `/unban`\n"
        "• `/autodel <seconds>` • `/fsub <id1,id2>` • `/publicmode <on|off>`",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="back_start")]]
        ),
    )


@Client.on_callback_query(filters.regex("^back_start$"))
async def back_cb(client: Client, query: CallbackQuery):
    await query.message.edit_text(
        f"👋 **Welcome back, {query.from_user.first_name}!**\n\nSend any file or open your **Mini App Vault** to manage your stored files and texts.",
        reply_markup=_home_keyboard(),
    )
