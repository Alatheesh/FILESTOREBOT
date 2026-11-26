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
from bot.database import db


@Client.on_message(filters.command("search") & filters.private)
async def search_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "🔍 <b>Usage:</b> <code>/search &lt;keyword&gt;</code>",
            parse_mode=ParseMode.HTML,
        )

    query = message.text.split(None, 1)[1].strip()
    results = await db.search_user_items(message.from_user.id, query, limit=15)
    if not results:
        return await message.reply_text(
            f"😕 No items found in your vault for <code>{html.escape(query)}</code>.",
            parse_mode=ParseMode.HTML,
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
        f"🔎 <b>Your Vault Results for:</b> <code>{html.escape(query)}</code>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


@Client.on_inline_query()
async def inline_search(client: Client, inline_query: InlineQuery):
    query = inline_query.query.strip()
    items = await db.search_user_items(inline_query.from_user.id, query, limit=25)
    articles = []
    for item in items:
        link = f"https://t.me/{client.me.username}?start={item['slug']}"
        safe_title = html.escape(item["title"])
        articles.append(
            InlineQueryResultArticle(
                title=item["title"],
                description=f"Type: {item['type'].upper()} • Downloads: {item.get('downloads', 0)}",
                input_message_content=InputTextMessageContent(
                    f"📦 <b>{safe_title}</b>\n🔗 <a href='{link}'>Click Here to Open</a>",
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📥 Get File / Text", url=link)]]
                ),
            )
        )
    await inline_query.answer(articles, cache_time=2, is_personal=True)
