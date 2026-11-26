from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from bot.database import db


@Client.on_message(filters.command("search") & filters.private)
async def search_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("🔍 **Usage:** `/search <keyword>`")

    query = message.text.split(None, 1)[1].strip()
    results = await db.search_items(query, limit=10)
    if not results:
        return await message.reply_text(f"😕 No stored files or texts found for `{query}`.")

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
        f"🔎 **Search Results for:** `{query}`",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_inline_query()
async def inline_search(client: Client, inline_query: InlineQuery):
    query = inline_query.query.strip()
    items = await db.search_items(query or ".*", limit=20)
    articles = []
    for item in items:
        link = f"https://t.me/{client.me.username}?start={item['slug']}"
        articles.append(
            InlineQueryResultArticle(
                title=item["title"],
                description=f"Type: {item['type'].upper()} • Downloads: {item.get('downloads', 0)}",
                input_message_content=InputTextMessageContent(
                    f"📦 **{item['title']}**\n🔗 [Click Here to Open]({link})",
                    disable_web_page_preview=True,
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📥 Get File / Text", url=link)]]
                ),
            )
        )
    await inline_query.answer(articles, cache_time=5)
