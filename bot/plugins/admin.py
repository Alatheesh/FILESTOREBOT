import asyncio
import html
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, LinkPreviewOptions
from pyrogram.errors import FloodWait
from bot.config import Config
from bot.database import db

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def admin_only(_, __, message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in Config.ADMIN_IDS)


admin_filter = filters.create(admin_only)


@Client.on_message(filters.command("stats") & filters.private & admin_filter)
async def stats_cmd(client: Client, message: Message):
    users = await db.count_users()
    items = await db.count_items()
    auto_del = await db.get_setting("auto_delete", Config.AUTO_DELETE_SECONDS)
    pub = await db.get_setting("public_uploads", True)
    await message.reply_text(
        f"📊 <b>Vault Bot Statistics</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{users}</code>\n"
        f"🗂 <b>Total Stored Items:</b> <code>{items}</code>\n"
        f"🌐 <b>Public Uploads:</b> <code>{pub}</code>\n"
        f"⏳ <b>Auto-Delete Timer:</b> <code>{auto_del}s</code>"
        f"{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("publicmode") & filters.private & admin_filter)
async def publicmode_cmd(client: Client, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in ("on", "off"):
        return await message.reply_text(
            f"Usage: <code>/publicmode on</code> or <code>/publicmode off</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    enabled = message.command[1].lower() == "on"
    await db.set_setting("public_uploads", enabled)
    await message.reply_text(
        f"🌐 Public multi-user uploads set to: <code>{enabled}</code>{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("broadcast") & filters.private & admin_filter)
async def broadcast_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text(
            f"📢 Reply to any message with <code>/broadcast</code> to send it to all users.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    status = await message.reply_text("⏳ Broadcasting...")
    sent = failed = 0
    async for user in await db.get_all_users():
        try:
            await message.reply_to_message.copy(user["user_id"])
            sent += 1
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ <b>Broadcast Complete</b>\n• Sent: <code>{sent}</code>\n• Failed: <code>{failed}</code>{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("ban") & filters.private & admin_filter)
async def ban_cmd(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/ban &lt;user_id&gt;</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    uid = int(message.command[1])
    await db.set_ban(uid, True)
    await message.reply_text(
        f"🚫 User <code>{uid}</code> has been banned.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("unban") & filters.private & admin_filter)
async def unban_cmd(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/unban &lt;user_id&gt;</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    uid = int(message.command[1])
    await db.set_ban(uid, False)
    await message.reply_text(
        f"✅ User <code>{uid}</code> has been unbanned.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("autodel") & filters.private & admin_filter)
async def autodel_cmd(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/autodel &lt;seconds&gt;</code> (use <code>0</code> to disable){Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    secs = int(message.command[1])
    await db.set_setting("auto_delete", secs)
    await message.reply_text(
        f"⏳ Auto-delete timer updated to <code>{secs}</code> seconds.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("fsub") & filters.private & admin_filter)
async def fsub_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"Usage: <code>/fsub -100111,-100222</code> (or <code>/fsub off</code>){Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    arg = message.command[1].strip()
    if arg.lower() == "off":
        await db.set_setting("fsub_channels", [])
        return await message.reply_text(
            f"🔓 Force-Subscribe disabled.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    ids = [int(x.strip()) for x in arg.split(",") if x.strip().lstrip("-").isdigit()]
    await db.set_setting("fsub_channels", ids)
    await message.reply_text(
        f"🔒 Force-Subscribe channels updated: <code>{html.escape(str(ids))}</code>{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )
