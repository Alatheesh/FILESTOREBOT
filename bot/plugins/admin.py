import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from bot.config import Config
from bot.database import db


def admin_only(_, __, message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in Config.ADMIN_IDS)


admin_filter = filters.create(admin_only)


@Client.on_message(filters.command("stats") & filters.private & admin_filter)
async def stats_cmd(client: Client, message: Message):
    users = await db.count_users()
    items = await db.count_items()
    auto_del = await db.get_setting("auto_delete", Config.AUTO_DELETE_SECONDS)
    await message.reply_text(
        f"📊 **Vault Bot Statistics**\n\n"
        f"👥 **Total Users:** `{users}`\n"
        f"🗂 **Stored Items:** `{items}`\n"
        f"⏳ **Auto-Delete Timer:** `{auto_del}s`"
    )


@Client.on_message(filters.command("broadcast") & filters.private & admin_filter)
async def broadcast_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("📢 Reply to any message with `/broadcast` to send it to all users.")

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

    await status.edit_text(f"✅ **Broadcast Complete**\n• Sent: `{sent}`\n• Failed: `{failed}`")


@Client.on_message(filters.command("ban") & filters.private & admin_filter)
async def ban_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/ban <user_id>`")
    uid = int(message.command[1])
    await db.set_ban(uid, True)
    await message.reply_text(f"🚫 User `{uid}` has been banned.")


@Client.on_message(filters.command("unban") & filters.private & admin_filter)
async def unban_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/unban <user_id>`")
    uid = int(message.command[1])
    await db.set_ban(uid, False)
    await message.reply_text(f"✅ User `{uid}` has been unbanned.")


@Client.on_message(filters.command("autodel") & filters.private & admin_filter)
async def autodel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/autodel <seconds>` (use `0` to disable)")
    secs = int(message.command[1])
    await db.set_setting("auto_delete", secs)
    await message.reply_text(f"⏳ Auto-delete timer updated to `{secs}` seconds.")


@Client.on_message(filters.command("fsub") & filters.private & admin_filter)
async def fsub_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/fsub -100111,-100222` (or `/fsub off`)")
    arg = message.command[1].strip()
    if arg.lower() == "off":
        await db.set_setting("fsub_channels", [])
        return await message.reply_text("🔓 Force-Subscribe disabled.")
    ids = [int(x.strip()) for x in arg.split(",") if x.strip().lstrip("-").isdigit()]
    await db.set_setting("fsub_channels", ids)
    await message.reply_text(f"🔒 Force-Subscribe channels updated: `{ids}`")
