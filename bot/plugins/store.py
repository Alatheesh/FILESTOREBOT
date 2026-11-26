import asyncio
import html
import re
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, ChannelPrivate, ChatAdminRequired, PeerIdInvalid, UserNotParticipant
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    LinkPreviewOptions,
)
from bot.config import Config
from bot.database import db
from bot.shortener import shorten_url
from bot.delivery import deliver_item, check_item_availability, destroy_expired_item
from bot.plugins.start import PENDING_PIN_USERS

WIZARD_SESSIONS: dict[int, dict] = {}
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_CHANNEL_BATCH_SIZE = 100


async def _notify_failover_if_needed(client: Client, alert_html: str):
    if not alert_html:
        return
    for admin_id in Config.ADMIN_IDS:
        try:
            await client.send_message(
                admin_id,
                f"{alert_html}{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )
        except Exception:
            pass


async def _is_allowed_uploader(user_id: int) -> bool:
    if await db.is_banned(user_id):
        return False
    if user_id in Config.ADMIN_IDS:
        return True
    return bool(await db.get_setting("public_uploads", True))


def _parse_post_ref(token: str) -> tuple[int | str | None, int | None]:
    token = token.strip().rstrip("/")
    if token.isdigit():
        return None, int(token)

    priv_match = re.search(r"(?:https?://)?t\.me/c/(\d+)/(\d+)", token)
    if priv_match:
        chat_id = int(f"-100{priv_match.group(1)}")
        msg_id = int(priv_match.group(2))
        return chat_id, msg_id

    pub_match = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,})/(\d+)", token)
    if pub_match and pub_match.group(1).lower() != "c":
        return pub_match.group(1), int(pub_match.group(2))

    return None, None


def _describe_message(message: Message, fallback_index: int) -> dict:
    if message.media:
        media_obj = getattr(message, message.media.value, None)
        label = (
            getattr(media_obj, "file_name", None)
            or message.caption
            or f"{message.media.value.title()} #{fallback_index}"
        )
        return {"title": label[:90], "type": message.media.value}
    if message.text:
        snippet = message.text.strip().splitlines()[0][:60]
        return {"title": f"Text: {snippet}", "type": "text"}
    return {"title": f"Item #{fallback_index}", "type": "item"}


async def _make_share_reply(client: Client, slug: str, title: str) -> tuple[str, InlineKeyboardMarkup]:
    direct_url = f"https://t.me/{client.me.username}?start={slug}"
    final_url = await shorten_url(direct_url)
    safe_title = html.escape(title)
    text = (
        f"✅ <b>Stored in Your Vault!</b>\n\n"
        f"📌 <b>Title:</b> <code>{safe_title}</code>\n"
        f"🔗 <b>Link:</b> {final_url}"
        f"{Config.CREDITS_HTML}"
    )
    rows = [
        [
            InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={final_url}"),
            InlineKeyboardButton("📥 Get Now", url=direct_url),
        ]
    ]
    if Config.WEBAPP_URL:
        rows.append(
            [
                InlineKeyboardButton(
                    "📱 Manage in Mini App",
                    web_app=WebAppInfo(url=f"{Config.WEBAPP_URL}/app"),
                )
            ]
        )
    return text, InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("text") & filters.private)
async def store_text_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    raw = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    if "|" not in raw:
        return await message.reply_text(
            f"📝 <b>Usage:</b> <code>/text Note Title | Your full text content here</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title, content = [part.strip() for part in raw.split("|", 1)]
    copied = await client.send_message(
        Config.DB_CHANNEL_ID,
        f"📝 <b>{html.escape(title)}</b>\n\n{html.escape(content)}",
        parse_mode=ParseMode.HTML,
    )
    slug, failover_alert = await db.save_item(
        item_type="text",
        message_ids=[copied.id],
        title=title[:120],
        created_by=user.id,
        owner_name=user.first_name or "",
        text_content=content,
        mime_type="text/plain",
        sub_items=[{"msg_id": copied.id, "title": title[:90], "type": "text"}],
    )
    await _notify_failover_if_needed(client, failover_alert)
    reply_text, kb = await _make_share_reply(client, slug, title[:120])
    await message.reply_text(
        reply_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("wizard") & filters.private)
async def start_wizard(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": [], "sub_items": []}
    await message.reply_text(
        f"🧙‍♂️ <b>Batch Wizard Started</b> (<code>{html.escape(title[:120])}</code>)\n\n"
        "Send as many <b>files, videos, photos, audio, or text messages</b> as you want.\n"
        "• Send <code>/done</code> when finished to save into your Mini App Vault.\n"
        f"• Send <code>/cancel</code> to abort.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_wizard(client: Client, message: Message):
    if WIZARD_SESSIONS.pop(message.from_user.id, None):
        await message.reply_text(
            f"❌ Wizard / Batch session cancelled.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )


@Client.on_message(filters.command("done") & filters.private)
async def finish_wizard(client: Client, message: Message):
    user = message.from_user
    session = WIZARD_SESSIONS.pop(user.id, None)
    if not session or not session["msg_ids"]:
        return await message.reply_text(
            f"⚠️ No items collected in your active session.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    slug, failover_alert = await db.save_item(
        item_type="batch",
        message_ids=session["msg_ids"],
        title=session["title"],
        created_by=user.id,
        owner_name=user.first_name or "",
        sub_items=session["sub_items"],
    )
    await _notify_failover_if_needed(client, failover_alert)
    reply_text, kb = await _make_share_reply(
        client, slug, f"{session['title']} ({len(session['msg_ids'])} items)"
    )
    await message.reply_text(
        reply_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(filters.command("batch") & filters.private)
async def batch_range_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await _is_allowed_uploader(user.id):
        return await message.reply_text(
            f"🔒 Uploads are currently restricted.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    args = message.command[1:]
    chat1, start_id = _parse_post_ref(args[0]) if len(args) >= 1 else (None, None)
    chat2, end_id = _parse_post_ref(args[1]) if len(args) >= 2 else (None, None)

    if start_id is not None and end_id is not None:
        source_chat = chat1 or chat2

        if source_chat is None:
            if user.id not in Config.ADMIN_IDS:
                return await message.reply_text(
                    "⚠️ <b>Channel Post Links Required</b>\n\n"
                    "Please pass full Telegram post links for the first and last message:\n"
                    "• <b>Public Channel:</b> <code>/batch https://t.me/channel/10 https://t.me/channel/25 My Title</code>\n"
                    "• <b>Private Channel:</b> Add this bot as an <b>Admin</b> in your private channel first, then use <code>/batch https://t.me/c/123456/10 https://t.me/c/123456/25 My Title</code>"
                    f"{Config.CREDITS_HTML}",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                )
            source_chat = Config.DB_CHANNEL_ID
        elif chat1 and chat2 and str(chat1).lower() != str(chat2).lower():
            return await message.reply_text(
                f"❌ Both post links must belong to the <b>same channel</b>.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        low_id, high_id = min(start_id, end_id), max(start_id, end_id)
        total_range = high_id - low_id + 1
        if total_range > MAX_CHANNEL_BATCH_SIZE:
            return await message.reply_text(
                f"⚠️ Maximum <b>{MAX_CHANNEL_BATCH_SIZE}</b> messages per batch (you requested <code>{total_range}</code>).{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        try:
            chat_info = await client.get_chat(source_chat)
        except (ChannelPrivate, ChatAdminRequired, PeerIdInvalid):
            return await message.reply_text(
                "🔒 <b>Private Channel Access Required!</b>\n\n"
                "I cannot read posts from this private channel yet.\n"
                "<b>How to fix:</b>\n"
                f"1. Open your private channel → <b>Administrators</b> → <b>Add Admin</b> → select <code>@{client.me.username}</code>.\n"
                "2. Grant it basic channel permissions and send the <code>/batch</code> links again!"
                f"{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )
        except Exception as e:
            return await message.reply_text(
                f"❌ Could not access that channel: <code>{html.escape(str(e))}</code>{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        is_private_channel = not bool(getattr(chat_info, "username", None))
        if is_private_channel and source_chat != Config.DB_CHANNEL_ID:
            try:
                bot_member = await client.get_chat_member(chat_info.id, "me")
                if bot_member.status.name not in ("ADMINISTRATOR", "OWNER"):
                    raise ChatAdminRequired
            except Exception:
                return await message.reply_text(
                    "🔒 <b>Admin Permission Needed in Private Channel</b>\n\n"
                    f"Please promote <code>@{client.me.username}</code> to <b>Administrator</b> in <b>{html.escape(chat_info.title or 'your private channel')}</b> so it can read and copy the batch posts."
                    f"{Config.CREDITS_HTML}",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                )

            try:
                user_member = await client.get_chat_member(chat_info.id, user.id)
                if user_member.status.name in ("BANNED", "LEFT"):
                    raise UserNotParticipant
            except Exception:
                return await message.reply_text(
                    f"🚫 You must be a member/admin of <b>{html.escape(chat_info.title or 'this private channel')}</b> to batch its files.{Config.CREDITS_HTML}",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                )

        title = " ".join(args[2:]).strip() if len(args) > 2 else f"{chat_info.title or 'Batch'} ({low_id}-{high_id})"

        if chat_info.id == Config.DB_CHANNEL_ID:
            msg_ids = list(range(low_id, high_id + 1))
            sub_items = [
                {"msg_id": mid, "title": f"Part #{idx + 1}", "type": "media"}
                for idx, mid in enumerate(msg_ids)
            ]
            slug, failover_alert = await db.save_item(
                item_type="batch",
                message_ids=msg_ids,
                title=title[:120],
                created_by=user.id,
                owner_name=user.first_name or "",
                sub_items=sub_items,
            )
            await _notify_failover_if_needed(client, failover_alert)
            reply_text, kb = await _make_share_reply(client, slug, title[:120])
            return await message.reply_text(
                reply_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        status_msg = await message.reply_text(
            f"⏳ <b>Importing {total_range} post(s)</b> from <b>{html.escape(chat_info.title or 'channel')}</b> into your vault...{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

        copied_ids: list[int] = []
        sub_items: list[dict] = []
        target_ids = list(range(low_id, high_id + 1))

        try:
            fetched_msgs = await client.get_messages(chat_info.id, target_ids)
            if not isinstance(fetched_msgs, list):
                fetched_msgs = [fetched_msgs]
        except Exception as e:
            return await status_msg.edit_text(
                f"❌ Failed to read channel posts: <code>{html.escape(str(e))}</code>{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        for src_msg in fetched_msgs:
            if not src_msg or src_msg.empty or src_msg.service:
                continue
            try:
                copied = await src_msg.copy(Config.DB_CHANNEL_ID)
                idx = len(copied_ids) + 1
                meta = _describe_message(src_msg, idx)
                copied_ids.append(copied.id)
                sub_items.append(
                    {"msg_id": copied.id, "title": meta["title"], "type": meta["type"]}
                )
                await asyncio.sleep(0.35)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    copied = await src_msg.copy(Config.DB_CHANNEL_ID)
                    idx = len(copied_ids) + 1
                    meta = _describe_message(src_msg, idx)
                    copied_ids.append(copied.id)
                    sub_items.append(
                        {"msg_id": copied.id, "title": meta["title"], "type": meta["type"]}
                    )
                except Exception:
                    continue
            except Exception:
                continue

        if not copied_ids:
            return await status_msg.edit_text(
                "⚠️ No copyable media or text posts were found in that message range (or the channel has content-saving restrictions enabled)."
                f"{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        slug, failover_alert = await db.save_item(
            item_type="batch",
            message_ids=copied_ids,
            title=title[:120],
            created_by=user.id,
            owner_name=user.first_name or "",
            sub_items=sub_items,
        )
        await _notify_failover_if_needed(client, failover_alert)
        reply_text, kb = await _make_share_reply(
            client, slug, f"{title[:120]} ({len(copied_ids)} items)"
        )
        return await status_msg.edit_text(
            reply_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    title = " ".join(args).strip() if args else "Untitled Bundle"
    WIZARD_SESSIONS[user.id] = {"title": title[:120], "msg_ids": [], "sub_items": []}
    await message.reply_text(
        f"🧙‍♂️ <b>Interactive Batch Started</b> (<code>{html.escape(title[:120])}</code>)\n\n"
        "• Forward or send all the <b>files, videos, photos, or text messages</b> you want to bundle, then type <code>/done</code>.\n"
        "• Or use <b>Channel Link Mode</b> anytime:\n"
        "  <code>/batch https://t.me/channel/10 https://t.me/channel/25 Bundle Title</code>\n"
        f"• Type <code>/cancel</code> to abort.{Config.CREDITS_HTML}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_message(
    filters.private
    & ~filters.command(
        [
            "start",
            "help",
            "about",
            "text",
            "wizard",
            "done",
            "cancel",
            "batch",
            "search",
            "stats",
            "broadcast",
            "ban",
            "unban",
            "autodel",
            "fsub",
            "publicmode",
            "dbstats",
            "adddb",
            "switchdb",
            "dblimit",
        ]
    )
)
async def handle_incoming_storage(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")

    if user.id in PENDING_PIN_USERS and message.text:
        entered_pin = message.text.strip()
        slug = PENDING_PIN_USERS.get(user.id)
        item = await db.get_item(slug) if slug else None
        if not item:
            PENDING_PIN_USERS.pop(user.id, None)
            return await message.reply_text(
                f"❌ This link is no longer available.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        available, _ = check_item_availability(item, user.id)
        if not available:
            PENDING_PIN_USERS.pop(user.id, None)
            await destroy_expired_item(client, item)
            return await message.reply_text(
                f"⌛ This link has expired or reached its view limit.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

        if entered_pin == item.get("pin_code"):
            PENDING_PIN_USERS.pop(user.id, None)
            await message.reply_text(
                f"🔓 <b>PIN Verified!</b> Delivering your item...{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )
            return await deliver_item(client, message.chat.id, item)
        else:
            return await message.reply_text(
                f"❌ <b>Incorrect PIN.</b> Try again or send <code>/start</code> to cancel.{Config.CREDITS_HTML}",
                parse_mode=ParseMode.HTML,
                link_preview_options=NO_PREVIEW,
            )

    if not await _is_allowed_uploader(user.id):
        return

    if user.id in WIZARD_SESSIONS:
        copied = await message.copy(Config.DB_CHANNEL_ID)
        idx = len(WIZARD_SESSIONS[user.id]["msg_ids"]) + 1
        meta = _describe_message(message, idx)
        WIZARD_SESSIONS[user.id]["msg_ids"].append(copied.id)
        WIZARD_SESSIONS[user.id]["sub_items"].append(
            {"msg_id": copied.id, "title": meta["title"], "type": meta["type"]}
        )
        return await message.reply_text(
            f"➕ Added <b>{html.escape(meta['title'])}</b> (#{idx}) to bundle. Send more or type <code>/done</code>.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

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

        slug, failover_alert = await db.save_item(
            item_type="single",
            message_ids=[copied.id],
            title=title[:120],
            created_by=user.id,
            owner_name=user.first_name or "",
            file_size=file_size,
            mime_type=mime_type,
            sub_items=[{"msg_id": copied.id, "title": title[:90], "type": message.media.value}],
        )
        await _notify_failover_if_needed(client, failover_alert)
        reply_text, kb = await _make_share_reply(client, slug, title[:120])
        await message.reply_text(
            reply_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
