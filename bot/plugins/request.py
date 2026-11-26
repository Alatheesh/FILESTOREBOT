from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config import Config


@Client.on_message(filters.command("request") & filters.private)
async def request_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("📩 **Usage:** `/request <name of file or content you want>`")

    req_text = message.text.split(None, 1)[1].strip()
    user = message.from_user
    alert = (
        f"📨 **New Content Request**\n\n"
        f"👤 **From:** {user.mention} (`{user.id}`)\n"
        f"📝 **Request:** {req_text}"
    )
    for admin_id in Config.ADMIN_IDS:
        try:
            await client.send_message(admin_id, alert)
        except Exception:
            pass

    await message.reply_text("✅ Your request has been sent to the admins!")
