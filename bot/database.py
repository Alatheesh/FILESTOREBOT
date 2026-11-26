import datetime
import secrets
from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import Config


class Database:
    def __init__(self):
        self.client = AsyncIOMotorClient(Config.MONGO_URI)
        self.db = self.client[Config.DB_NAME]
        self.users = self.db["users"]
        self.items = self.db["items"]
        self.settings = self.db["settings"]

    async def init_indexes(self):
        await self.users.create_index("user_id", unique=True)
        await self.items.create_index("slug", unique=True)
        await self.items.create_index([("title", "text"), ("tags", "text")])

    # --- Users ---
    async def add_user(self, user_id: int, first_name: str = ""):
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {"first_name": first_name, "last_seen": datetime.datetime.utcnow()},
                "$setOnInsert": {"joined_at": datetime.datetime.utcnow(), "banned": False},
            },
            upsert=True,
        )

    async def is_banned(self, user_id: int) -> bool:
        doc = await self.users.find_one({"user_id": user_id}, {"banned": 1})
        return bool(doc and doc.get("banned"))

    async def set_ban(self, user_id: int, banned: bool):
        await self.users.update_one({"user_id": user_id}, {"$set": {"banned": banned}}, upsert=True)

    async def get_all_users(self):
        return self.users.find({"banned": {"$ne": True}}, {"user_id": 1})

    async def count_users(self) -> int:
        return await self.users.count_documents({})

    # --- Stored Files, Texts & Batches ---
    async def save_item(
        self,
        item_type: str,  # "single" | "batch" | "text"
        message_ids: list[int],
        title: str,
        created_by: int,
        text_content: str = "",
        file_size: int = 0,
        mime_type: str = "",
    ) -> str:
        slug = secrets.token_urlsafe(7)
        await self.items.insert_one(
            {
                "slug": slug,
                "type": item_type,
                "message_ids": message_ids,
                "title": title,
                "text_content": text_content,
                "file_size": file_size,
                "mime_type": mime_type,
                "created_by": created_by,
                "downloads": 0,
                "created_at": datetime.datetime.utcnow(),
            }
        )
        return slug

    async def get_item(self, slug: str) -> dict | None:
        return await self.items.find_one({"slug": slug})

    async def increment_downloads(self, slug: str):
        await self.items.update_one({"slug": slug}, {"$inc": {"downloads": 1}})

    async def search_items(self, query: str, limit: int = 15) -> list[dict]:
        cursor = self.items.find(
            {"title": {"$regex": query, "$options": "i"}}
        ).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def count_items(self) -> int:
        return await self.items.count_documents({})

    # --- Dynamic Settings ---
    async def get_setting(self, key: str, default=None):
        doc = await self.settings.find_one({"_id": key})
        return doc["value"] if doc else default

    async def set_setting(self, key: str, value):
        await self.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)


db = Database()
