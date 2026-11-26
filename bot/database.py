import datetime
import logging
import secrets
from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import Config

logger = logging.getLogger("VaultBot.MultiDB")


class MultiDatabaseManager:
    def __init__(self):
        self.clients: list[AsyncIOMotorClient] = []
        self.dbs = []
        self.uris: list[str] = []
        self.active_index: int = 0
        self.max_size_mb: float = Config.DB_MAX_SIZE_MB
        self._writes_since_check: int = 0

        for idx, uri in enumerate(Config.MONGO_URIS):
            self._register_uri(uri, label=f"DB #{idx + 1}")

    def _register_uri(self, uri: str, label: str = "") -> int:
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=8000)
        database = client[Config.DB_NAME]
        self.clients.append(client)
        self.dbs.append(database)
        self.uris.append(uri)
        return len(self.dbs) - 1

    @property
    def primary_db(self):
        return self.dbs[0]

    @property
    def active_db(self):
        return self.dbs[self.active_index]

    async def init_indexes(self):
        if not self.dbs:
            raise RuntimeError("No MongoDB URIs configured! Set MONGO_URIS or MONGO_URI.")

        for idx, database in enumerate(self.dbs):
            try:
                await database["users"].create_index("user_id", unique=True)
                await database["items"].create_index("slug", unique=True)
                await database["items"].create_index([("created_by", 1), ("created_at", -1)])
                await database["items"].create_index([("created_by", 1), ("title", 1)])
                logger.info(f"Initialized indexes on DB #{idx + 1}")
            except Exception as e:
                logger.warning(f"Could not init indexes on DB #{idx + 1}: {e}")

        extra_uris = await self.get_setting("extra_mongo_uris", [])
        for uri in extra_uris:
            if uri and uri not in self.uris:
                new_idx = self._register_uri(uri)
                try:
                    await self.dbs[new_idx]["items"].create_index("slug", unique=True)
                    await self.dbs[new_idx]["items"].create_index([("created_by", 1), ("created_at", -1)])
                    await self.dbs[new_idx]["items"].create_index([("created_by", 1), ("title", 1)])
                except Exception:
                    pass

        saved_limit = await self.get_setting("db_max_size_mb", None)
        if saved_limit is not None:
            self.max_size_mb = float(saved_limit)

        await self.ensure_writable_db(force_check=True)

    async def get_db_usage_mb(self, index: int) -> dict:
        database = self.dbs[index]
        try:
            stats = await database.command("dbStats")
            data_bytes = stats.get("dataSize", 0) + stats.get("indexSize", 0)
            storage_bytes = stats.get("storageSize", 0) + stats.get("indexSize", 0)
            used_mb = round(max(data_bytes, storage_bytes) / (1024 * 1024), 2)
            item_count = await database["items"].count_documents({})
            return {
                "index": index,
                "label": f"DB #{index + 1}",
                "online": True,
                "used_mb": used_mb,
                "limit_mb": self.max_size_mb,
                "percent": round((used_mb / self.max_size_mb) * 100, 1) if self.max_size_mb > 0 else 0,
                "items": item_count,
            }
        except Exception as e:
            return {
                "index": index,
                "label": f"DB #{index + 1}",
                "online": False,
                "used_mb": -1,
                "limit_mb": self.max_size_mb,
                "percent": 100.0,
                "items": 0,
                "error": str(e),
            }

    async def get_all_db_stats(self) -> list[dict]:
        results = []
        for idx in range(len(self.dbs)):
            info = await self.get_db_usage_mb(idx)
            info["is_active"] = (idx == self.active_index)
            results.append(info)
        return results

    async def ensure_writable_db(self, force_check: bool = False) -> tuple[bool, str]:
        self._writes_since_check += 1
        if not force_check and self._writes_since_check < 5:
            return False, ""
        self._writes_since_check = 0

        current_info = await self.get_db_usage_mb(self.active_index)
        if current_info["online"] and current_info["used_mb"] < self.max_size_mb:
            return False, ""

        old_idx = self.active_index
        for candidate_idx in range(len(self.dbs)):
            if candidate_idx == old_idx:
                continue
            info = await self.get_db_usage_mb(candidate_idx)
            if info["online"] and info["used_mb"] < self.max_size_mb:
                self.active_index = candidate_idx
                msg = (
                    f"⚠️ <b>Auto-Failover Triggered!</b>\n\n"
                    f"• <b>Previous:</b> DB #{old_idx + 1} ({current_info['used_mb']} MB / {self.max_size_mb} MB)\n"
                    f"• <b>New Active:</b> DB #{candidate_idx + 1} ({info['used_mb']} MB used)\n"
                    "All new files, batches, and texts will now store automatically in the new database."
                )
                logger.warning(msg)
                return True, msg

        return False, ""

    async def set_active_db(self, index: int) -> bool:
        if 0 <= index < len(self.dbs):
            self.active_index = index
            return True
        return False

    async def add_runtime_uri(self, uri: str) -> tuple[bool, str]:
        uri = uri.strip()
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            return False, "URI must start with mongodb:// or mongodb+srv://"
        if uri in self.uris:
            return False, "This MongoDB URI is already in the pool."

        new_idx = self._register_uri(uri)
        info = await self.get_db_usage_mb(new_idx)
        if not info["online"]:
            self.clients.pop()
            self.dbs.pop()
            self.uris.pop()
            return False, f"Connection failed: {info.get('error', 'unreachable')}"

        try:
            await self.dbs[new_idx]["items"].create_index("slug", unique=True)
            await self.dbs[new_idx]["items"].create_index([("created_by", 1), ("created_at", -1)])
            await self.dbs[new_idx]["items"].create_index([("created_by", 1), ("title", 1)])
        except Exception:
            pass

        extra_uris = await self.get_setting("extra_mongo_uris", [])
        extra_uris.append(uri)
        await self.set_setting("extra_mongo_uris", extra_uris)
        return True, f"Added as DB #{new_idx + 1} ({info['used_mb']} MB used)"

    # --- Users & Terms Consent ---
    async def add_user(self, user_id: int, first_name: str = ""):
        await self.primary_db["users"].update_one(
            {"user_id": user_id},
            {
                "$set": {"first_name": first_name, "last_seen": datetime.datetime.utcnow()},
                "$setOnInsert": {
                    "joined_at": datetime.datetime.utcnow(),
                    "banned": False,
                    "accepted_terms": False,
                },
            },
            upsert=True,
        )

    async def has_accepted_terms(self, user_id: int) -> bool:
        if user_id in Config.ADMIN_IDS:
            return True
        doc = await self.primary_db["users"].find_one({"user_id": user_id}, {"accepted_terms": 1})
        return bool(doc and doc.get("accepted_terms"))

    async def accept_terms(self, user_id: int):
        await self.primary_db["users"].update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "accepted_terms": True,
                    "accepted_terms_at": datetime.datetime.utcnow(),
                }
            },
            upsert=True,
        )

    async def is_banned(self, user_id: int) -> bool:
        doc = await self.primary_db["users"].find_one({"user_id": user_id}, {"banned": 1})
        return bool(doc and doc.get("banned"))

    async def set_ban(self, user_id: int, banned: bool):
        await self.primary_db["users"].update_one(
            {"user_id": user_id}, {"$set": {"banned": banned}}, upsert=True
        )

    async def get_all_users(self):
        return self.primary_db["users"].find({"banned": {"$ne": True}}, {"user_id": 1})

    async def count_users(self) -> int:
        return await self.primary_db["users"].count_documents({})

    # --- Stored Files, Texts & Batches ---
    async def save_item(
        self,
        item_type: str,
        message_ids: list[int],
        title: str,
        created_by: int,
        owner_name: str = "",
        text_content: str = "",
        file_size: int = 0,
        mime_type: str = "",
        sub_items: list[dict] | None = None,
    ) -> tuple[str, str]:
        _, failover_alert = await self.ensure_writable_db(force_check=False)

        slug = secrets.token_urlsafe(7)
        if sub_items is None:
            sub_items = [
                {"msg_id": mid, "title": f"Item #{idx + 1}", "type": "media"}
                for idx, mid in enumerate(message_ids)
            ]

        await self.active_db["items"].insert_one(
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
                "pin_code": "",
                "expires_at": None,
                "max_downloads": 0,
                "db_index": self.active_index,
                "created_at": datetime.datetime.utcnow(),
            }
        )
        return slug, failover_alert

    async def get_item(self, slug: str) -> dict | None:
        order = [self.active_index] + [i for i in range(len(self.dbs)) if i != self.active_index]
        for idx in order:
            try:
                doc = await self.dbs[idx]["items"].find_one({"slug": slug})
                if doc:
                    doc["_db_idx"] = idx
                    return doc
            except Exception:
                continue
        return None

    async def increment_downloads(self, slug: str) -> int:
        for idx in range(len(self.dbs)):
            try:
                doc = await self.dbs[idx]["items"].find_one_and_update(
                    {"slug": slug},
                    {"$inc": {"downloads": 1}},
                    projection={"downloads": 1},
                    return_document=True,
                )
                if doc:
                    return doc.get("downloads", 0)
            except Exception:
                continue
        return 0

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

        combined: list[dict] = []
        for idx in range(len(self.dbs)):
            try:
                cursor = self.dbs[idx]["items"].find(filt, {"_id": 0}).limit(limit)
                docs = await cursor.to_list(length=limit)
                combined.extend(docs)
            except Exception:
                continue

        if sort_by == "oldest":
            combined.sort(key=lambda x: x.get("created_at") or datetime.datetime.min)
        elif sort_by == "name_asc":
            combined.sort(key=lambda x: (x.get("title") or "").lower())
        elif sort_by == "name_desc":
            combined.sort(key=lambda x: (x.get("title") or "").lower(), reverse=True)
        elif sort_by == "downloads":
            combined.sort(key=lambda x: int(x.get("downloads", 0)), reverse=True)
        else:
            combined.sort(key=lambda x: x.get("created_at") or datetime.datetime.min, reverse=True)

        return [self._serialize_item(d) for d in combined[:limit]]

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

        for idx in range(len(self.dbs)):
            try:
                if not updates:
                    doc = await self.dbs[idx]["items"].find_one(
                        {"slug": slug, "created_by": int(user_id)}, {"_id": 0}
                    )
                    if doc:
                        return self._serialize_item(doc)
                else:
                    res = await self.dbs[idx]["items"].find_one_and_update(
                        {"slug": slug, "created_by": int(user_id)},
                        {"$set": updates},
                        projection={"_id": 0},
                        return_document=True,
                    )
                    if res:
                        return self._serialize_item(res)
            except Exception:
                continue
        return None

    async def delete_user_item(self, slug: str, user_id: int) -> dict | None:
        for idx in range(len(self.dbs)):
            try:
                deleted = await self.dbs[idx]["items"].find_one_and_delete(
                    {"slug": slug, "created_by": int(user_id)}
                )
                if deleted:
                    return deleted
            except Exception:
                continue
        return None

    async def delete_item_by_slug(self, slug: str) -> dict | None:
        for idx in range(len(self.dbs)):
            try:
                deleted = await self.dbs[idx]["items"].find_one_and_delete({"slug": slug})
                if deleted:
                    return deleted
            except Exception:
                continue
        return None

    async def search_user_items(self, user_id: int, query: str, limit: int = 15) -> list[dict]:
        filt: dict = {"created_by": int(user_id)}
        if query:
            filt["title"] = {"$regex": query, "$options": "i"}
        merged: list[dict] = []
        for idx in range(len(self.dbs)):
            try:
                cursor = self.dbs[idx]["items"].find(filt).sort("created_at", -1).limit(limit)
                merged.extend(await cursor.to_list(length=limit))
            except Exception:
                continue
        merged.sort(key=lambda x: x.get("created_at") or datetime.datetime.min, reverse=True)
        return merged[:limit]

    async def count_items(self) -> int:
        total = 0
        for idx in range(len(self.dbs)):
            try:
                total += await self.dbs[idx]["items"].count_documents({})
            except Exception:
                continue
        return total

    # --- Dynamic Settings ---
    async def get_setting(self, key: str, default=None):
        doc = await self.primary_db["settings"].find_one({"_id": key})
        return doc["value"] if doc else default

    async def set_setting(self, key: str, value):
        await self.primary_db["settings"].update_one(
            {"_id": key}, {"$set": {"value": value}}, upsert=True
        )


db = MultiDatabaseManager()
