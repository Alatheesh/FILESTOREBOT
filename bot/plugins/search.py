import html
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
)
from bot.config import Config
from bot.database import db
from bot.plugins.start import consent_prompt_payload

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@Client.on_message(filters.command("search") & filters.private)
async def search_cmd(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.first_name or "")
    if not await db.has_accepted_terms(user.id):
        text, kb = consent_prompt_payload(user.first_name or "")
        return await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    if len(message.command) < 2:
        return await message.reply_text(
            f"🔍 <b>Usage:</b> <code>/search &lt;keyword&gt;</code>{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    query = message.text.split(None, 1)[1].strip()
    results = await db.search_user_items(user.id, query, limit=15)
    if not results:
        return await message.reply_text(
            f"😕 No items found in your vault for <code>{html.escape(query)}</code>.{Config.CREDITS_HTML}",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )

    buttons = [
        [
            InlineKeyboardButton(
                f"📁 {item['title'][:45]}",
                url=f"https://t.me/{client.me.username}?start={item['slug']}",
            )
        ]
        for item in results
    ]
    await message.reply_text(
        f"🔎 <b>Your Vault Results for:</b> <code>{html.escape(query)}</code>{Config.CREDITS_HTML}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
    )


@Client.on_inline_query()
async def inline_search(client: Client, inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    if not await db.has_accepted_terms(user_id):
        return await inline_query.answer(
            [],
            switch_pm_text="🔒 Accept Privacy Policy to Use Vault",
            switch_pm_parameter="terms",
            cache_time=1,
            is_personal=True,
        )

    query = inline_query.query.strip()
    items = await db.search_user_items(user_id, query, limit=25)
    articles = []
    for item in items:
        link = f"https://t.me/{client.me.username}?start={item['slug']}"
        safe_title = html.escape(item["title"])
        articles.append(
            InlineQueryResultArticle(
                title=item["title"],
                description=f"Type: {item['type'].upper()} • Downloads: {item.get('downloads', 0)}",
                input_message_content=InputTextMessageContent(
                    f"📦 <b>{safe_title}</b>\n🔗 <a href='{link}'>Click Here to Open</a>{Config.CREDITS_HTML}",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📥 Get File / Text", url=link)]]
                ),
            )
        )
    await inline_query.answer(articles, cache_time=2, is_personal=True)
