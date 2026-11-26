import asyncio
import datetime
import html
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import LinkPreviewOptions
from bot.config import Config
from bot.database import db

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def _schedule_delete(client: Client, chat_id: int, message_ids: list[int], delay: int):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except Exception:
        pass


def check_item_availability(item: dict, requester_id: int) -> tuple[bool, str]:
    is_owner = int(item.get("created_by", 0)) == int(requester_id)
    if is_owner:
        return True, ""

    expires_at = item.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.datetime.fromisoformat(expires_at.replace("Z", ""))
        except Exception:
            expires_at = None
    if isinstance(expires_at, datetime.datetime) and datetime.datetime.utcnow() > expires_at:
        return False, "expired"

    max_dl = int(item.get("max_downloads", 0) or 0)
    current_dl = int(item.get("downloads", 0) or 0)
    if max_dl > 0 and current_dl >= max_dl:
        return False, "limit_reached"

    return True, ""


async def destroy_expired_item(client: Client, item: dict):
    await db.delete_item_by_slug(item["slug"])
    msg_ids = item.get("message_ids", [])
    if msg_ids:
        try:
            await client.delete_messages(chat_id=Config.DB_CHANNEL_ID, message_ids=msg_ids)
        except Exception:
            pass


async def deliver_item(
    client: Client,
    chat_id: int,
    item: dict,
    single_msg_id: int | None = None,
):
    sent_ids: list[int] = []
    auto_del = await db.get_setting("auto_delete", Config.AUTO_DELETE_SECONDS)
    protect = await db.get_setting("protect_content", Config.PROTECT_CONTENT)

    if single_msg_id is not None:
        target_ids = [int(single_msg_id)]
    else:
        target_ids = item.get("message_ids", [])

    if item["type"] == "text" and item.get("text_content") and single_msg_id is None:
        safe_title = html.escape(item["title"])
        safe_body = html.escape(item["text_content"])
        msg = await client.send_message(
            chat_id=chat_id,
            text=f"📝 <b>{safe_title}</b>\n\n{safe_body}{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
            protect_content=protect,
        )
        sent_ids.append(msg.id)
    else:
        for msg_id in target_ids:
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

    new_downloads = await db.increment_downloads(item["slug"])

    max_dl = int(item.get("max_downloads", 0) or 0)
    is_owner = int(item.get("created_by", 0)) == int(chat_id)
    if not is_owner and max_dl > 0 and new_downloads >= max_dl:
        await destroy_expired_item(client, item)

    if auto_del and int(auto_del) > 0 and sent_ids:
        mins = round(int(auto_del) / 60, 1)
        warn = await client.send_message(
            chat_id=chat_id,
            text=(
                f"⏳ <b>Auto-Delete Active:</b> These messages will be deleted automatically in "
                f"<b>{mins} min(s)</b>. Save or forward them now.{Config.CREDITS_HTML}"
            ),
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
        sent_ids.append(warn.id)
        asyncio.create_task(_schedule_delete(client, chat_id, sent_ids, int(auto_del)))
