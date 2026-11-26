import asyncio
from pyrogram import Client
from pyrogram.errors import FloodWait
from bot.config import Config
from bot.database import db


async def _schedule_delete(client: Client, chat_id: int, message_ids: list[int], delay: int):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except Exception:
        pass


async def deliver_item(client: Client, chat_id: int, item: dict):
    sent_ids: list[int] = []
    auto_del = await db.get_setting("auto_delete", Config.AUTO_DELETE_SECONDS)
    protect = await db.get_setting("protect_content", Config.PROTECT_CONTENT)

    if item["type"] == "text" and item.get("text_content"):
        msg = await client.send_message(
            chat_id=chat_id,
            text=f"**{item['title']}**\n\n{item['text_content']}",
            protect_content=protect,
        )
        sent_ids.append(msg.id)
    else:
        for msg_id in item["message_ids"]:
            try:
                copied = await client.copy_message(
                    chat_id=chat_id,
                    from_chat_id=Config.DB_CHANNEL_ID,
                    message_id=msg_id,
                    protect_content=protect,
                )
                sent_ids.append(copied.id)
                await asyncio.sleep(0.35)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                copied = await client.copy_message(
                    chat_id=chat_id,
                    from_chat_id=Config.DB_CHANNEL_ID,
                    message_id=msg_id,
                    protect_content=protect,
                )
                sent_ids.append(copied.id)
            except Exception:
                continue

    await db.increment_downloads(item["slug"])

    if auto_del and int(auto_del) > 0 and sent_ids:
        mins = round(int(auto_del) / 60, 1)
        warn = await client.send_message(
            chat_id=chat_id,
            text=f"⏳ **Auto-Delete Active:** These messages will be deleted automatically in **{mins} min(s)**. Save or forward them now.",
        )
        sent_ids.append(warn.id)
        asyncio.create_task(_schedule_delete(client, chat_id, sent_ids, int(auto_del)))
