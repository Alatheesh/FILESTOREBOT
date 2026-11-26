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
        await self.items.create_index([("created_by", 1), ("created_at", -1)])
        await self.items.create_index([("created_by", 1), ("title", 1)])

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
        owner_name: str = "",
        text_content: str = "",
        file_size: int = 0,
        mime_type: str = "",
        sub_items: list[dict] | None = None,
    ) -> str:
        slug = secrets.token_urlsafe(7)
        if sub_items is None:
            sub_items = [
                {"msg_id": mid, "title": f"Item #{idx + 1}", "type": "media"}
                for idx, mid in enumerate(message_ids)
            ]

        await self.items.insert_one(
            {
                "slug": slug,
                "type": item_type,
                "message_ids": message_ids,
                "sub_items": sub_items,
                "title": title,
                "text_content": text_content,
                "file_size": file_size,
                "mime_type": mime_type,
                "created_by": int(created_by),
                "owner_name": owner_name,
                "downloads": 0,
                # Link Rules (Phase 3)
                "pin_code": "",
                "expires_at": None,
                "max_downloads": 0,
                "created_at": datetime.datetime.utcnow(),
            }
        )
        return slug

    async def get_item(self, slug: str) -> dict | None:
        return await self.items.find_one({"slug": slug})

    async def increment_downloads(self, slug: str) -> int:
        doc = await self.items.find_one_and_update(
            {"slug": slug},
            {"$inc": {"downloads": 1}},
            projection={"downloads": 1},
            return_document=True,
        )
        return doc.get("downloads", 0) if doc else 0

    def _serialize_item(self, d: dict) -> dict:
        if isinstance(d.get("created_at"), datetime.datetime):
            d["created_at"] = d["created_at"].isoformat() + "Z"
        if isinstance(d.get("expires_at"), datetime.datetime):
            d["expires_at"] = d["expires_at"].isoformat() + "Z"
        if not d.get("sub_items") and d.get("message_ids"):
            d["sub_items"] = [
                {"msg_id": mid, "title": f"Item #{i + 1}", "type": "media"}
                for i, mid in enumerate(d["message_ids"])
            ]
        return d

    async def get_user_items(
        self,
        user_id: int,
        query: str = "",
        item_type: str = "all",
        sort_by: str = "newest",
        limit: int = 200,
    ) -> list[dict]:
        filt: dict = {"created_by": int(user_id)}
        if query:
            filt["title"] = {"$regex": query, "$options": "i"}
        if item_type in ("single", "batch", "text"):
            filt["type"] = item_type

        sort_map = {
            "newest": [("created_at", -1)],
            "oldest": [("created_at", 1)],
            "name_asc": [("title", 1)],
            "name_desc": [("title", -1)],
            "downloads": [("downloads", -1)],
        }
        sort_spec = sort_map.get(sort_by, [("created_at", -1)])

        cursor = self.items.find(filt, {"_id": 0}).sort(sort_spec).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._serialize_item(d) for d in docs]

    async def update_user_item(
        self,
        slug: str,
        user_id: int,
        title: str | None = None,
        text_content: str | None = None,
        pin_code: str | None = None,
        expire_hours: int | None = None,
        max_downloads: int | None = None,
        sub_items: list[dict] | None = None,
    ) -> dict | None:
        updates: dict = {}
        if title is not None and title.strip():
            updates["title"] = title.strip()[:120]
        if text_content is not None:
            updates["text_content"] = text_content
        if pin_code is not None:
            clean_pin = "".join(ch for ch in str(pin_code) if ch.isdigit())[:4]
            updates["pin_code"] = clean_pin
        if expire_hours is not None:
            hrs = int(expire_hours)
            if hrs <= 0:
                updates["expires_at"] = None
            else:
                updates["expires_at"] = datetime.datetime.utcnow() + datetime.timedelta(hours=hrs)
        if max_downloads is not None:
            updates["max_downloads"] = max(0, int(max_downloads))
        if sub_items is not None:
            updates["sub_items"] = sub_items
            updates["message_ids"] = [int(x["msg_id"]) for x in sub_items]

        if not updates:
            doc = await self.items.find_one({"slug": slug, "created_by": int(user_id)}, {"_id": 0})
            return self._serialize_item(doc) if doc else None

        res = await self.items.find_one_and_update(
            {"slug": slug, "created_by": int(user_id)},
            {"$set": updates},
            projection={"_id": 0},
            return_document=True,
        )
        return self._serialize_item(res) if res else None

    async def delete_user_item(self, slug: str, user_id: int) -> dict | None:
        return await self.items.find_one_and_delete(
            {"slug": slug, "created_by": int(user_id)}
        )

    async def delete_item_by_slug(self, slug: str) -> dict | None:
        return await self.items.find_one_and_delete({"slug": slug})

    async def search_user_items(self, user_id: int, query: str, limit: int = 15) -> list[dict]:
        filt: dict = {"created_by": int(user_id)}
        if query:
            filt["title"] = {"$regex": query, "$options": "i"}
        cursor = self.items.find(filt).sort("created_at", -1).limit(limit)
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
