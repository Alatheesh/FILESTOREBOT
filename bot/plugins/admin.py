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
    db_stats = await db.get_all_db_stats()
    active_info = next((d for d in db_stats if d["is_active"]), None)
    active_str = (
        f"DB #{active_info['index'] + 1} ({active_info['used_mb']} / {active_info['limit_mb']} MB)"
        if active_info
        else "Unknown"
    )
    await message.reply_text(
        f"📊 <b>Vault Bot Statistics</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{users}</code>\n"
        f"🗂 <b>Total Stored Items:</b> <code>{items}</code>\n"
        f"🗄️ <b>Active Write DB:</b> <code>{active_str}</code> ({len(db_stats)} DBs in pool)\n"
        f"🌐 <b>Public Uploads:</b> <code>{pub}</code>\n"
        f"⏳ <b>Auto-Delete Timer:</b> <code>{auto_del}s</code>\n\n"
        f"<i>Use /dbstats to inspect all MongoDB clusters.</i>"
        f"{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("dbstats") & filters.private & admin_filter)
async def dbstats_cmd(client: Client, message: Message):
    all_stats = await db.get_all_db_stats()
    lines = ["🗄️ <b>Multi-MongoDB Storage Pool</b>\n"]
    for info in all_stats:
        status_icon = "🟢 ACTIVE" if info["is_active"] else ("🟡 STANDBY" if info["online"] else "🔴 OFFLINE")
        if info["online"]:
            lines.append(
                f"• <b>{info['label']}</b> [{status_icon}]\n"
                f"  Space: <code>{info['used_mb']} MB / {info['limit_mb']} MB</code> ({info['percent']}%) • Items: <code>{info['items']}</code>"
            )
        else:
            lines.append(f"• <b>{info['label']}</b> [{status_icon}] — Connection error")

    lines.append(
        "\n<b>Admin DB Commands:</b>\n"
        "• <code>/adddb &lt;mongodb_uri&gt;</code> — Add a new cluster live\n"
        "• <code>/switchdb &lt;number&gt;</code> — Manually switch active write DB\n"
        "• <code>/dblimit &lt;mb&gt;</code> — Set auto-failover threshold (default 460 MB)"
    )
    await message.reply_text(
        "\n".join(lines) + Config.CREDITS_HTML,
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("adddb") & filters.private & admin_filter)
async def adddb_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"🗄️ <b>Usage:</b> <code>/adddb mongodb+srv://user:pass@cluster.mongodb.net/...</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    new_uri = message.text.split(None, 1)[1].strip()
    try:
        await message.delete()
    except Exception:
        pass

    wait_msg = await client.send_message(
        message.chat.id, "⏳ Testing connection & initializing indexes on new MongoDB cluster..."
    )
    ok, msg = await db.add_runtime_uri(new_uri)
    icon = "✅" if ok else "❌"
    await wait_msg.edit_text(
        f"{icon} {html.escape(msg)}{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("switchdb") & filters.private & admin_filter)
async def switchdb_cmd(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/switchdb &lt;db_number&gt;</code> (e.g. <code>/switchdb 2</code>){Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    target_num = int(message.command[1])
    if await db.set_active_db(target_num - 1):
        await message.reply_text(
            f"✅ Active write database switched to <b>DB #{target_num}</b>.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    else:
        await message.reply_text(
            f"❌ Invalid DB number. Use <code>/dbstats</code> to see available databases.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )


@Client.on_message(filters.command("dblimit") & filters.private & admin_filter)
async def dblimit_cmd(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/dblimit &lt;megabytes&gt;</code> (e.g. <code>/dblimit 460</code> for 512 MB free tier){Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    mb = float(message.command[1])
    db.max_size_mb = mb
    await db.set_setting("db_max_size_mb", mb)
    await db.ensure_writable_db(force_check=True)
    await message.reply_text(
        f"✅ Auto-failover storage threshold set to <b>{mb} MB</b>.{Config.CREDITS_HTML}",
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
