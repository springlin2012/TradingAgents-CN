"""微信新用户自动注册：unionid 为空时不得占用唯一索引。"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.indexes = {}
        self.dropped_indexes = []
        self.insert_one_side_effect = None

    def create_index(self, keys, **kwargs):
        name = kwargs.get("name")
        if not name:
            field = keys if isinstance(keys, str) else keys[0][0]
            name = f"{field}_1"
        self.indexes[name] = {"name": name, "key": keys, **kwargs}
        return name

    def list_indexes(self):
        return list(self.indexes.values())

    def drop_index(self, name):
        self.dropped_indexes.append(name)
        self.indexes.pop(name, None)

    def update_one(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                self._apply_update(doc, update)
                return SimpleNamespace(modified_count=1, matched_count=1)
        return SimpleNamespace(modified_count=0, matched_count=0)

    def insert_one(self, doc):
        if self.insert_one_side_effect:
            raise self.insert_one_side_effect
        stored = dict(doc)
        stored.setdefault("_id", ObjectId())
        if "wechat_openid" in stored:
            for existing in self.docs:
                if existing.get("wechat_openid") == stored["wechat_openid"]:
                    raise DuplicateKeyError("E11000 duplicate wechat_openid")
        if "wechat_unionid" in stored:
            for existing in self.docs:
                if (
                    "wechat_unionid" in existing
                    and existing["wechat_unionid"] == stored["wechat_unionid"]
                ):
                    raise DuplicateKeyError("E11000 duplicate wechat_unionid")
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    def find_one(self, query, projection=None):
        if "$or" in query:
            for clause in query["$or"]:
                found = self.find_one(clause)
                if found:
                    return found
            return None
        for doc in self.docs:
            if self._match(doc, query):
                return dict(doc)
        return None

    @staticmethod
    def _match(doc, query):
        if "wechat_unionid" in query and isinstance(query["wechat_unionid"], dict):
            type_filter = query["wechat_unionid"].get("$type")
            if type_filter == "null":
                return "wechat_unionid" in doc and doc["wechat_unionid"] is None
        return all(doc.get(key) == value for key, value in query.items())

    @staticmethod
    def _apply_update(doc, update):
        if "$unset" in update:
            for key in update["$unset"]:
                doc.pop(key, None)
        if "$set" in update:
            doc.update(update["$set"])


class FakeClient:
    def __init__(self, collection):
        self._db = SimpleNamespace(users=collection)

    def __getitem__(self, name):
        return self._db

    def close(self):
        pass


with patch("app.services.user_service.MongoClient", lambda *a, **k: FakeClient(FakeCollection())):
    from app.services.user_service import UserService


def _build_service(monkeypatch, collection=None):
    collection = collection or FakeCollection()
    client = FakeClient(collection)
    monkeypatch.setattr("app.services.user_service.MongoClient", lambda *a, **k: client)
    return UserService(), collection


def test_new_user_doc_omits_none_fields(monkeypatch):
    service, _ = _build_service(monkeypatch)
    doc = service._new_user_doc(
        username="wx_demo",
        email="demo@wechat.local",
        wechat_openid="openid_demo",
        wechat_unionid=None,
        is_verified=True,
    )
    assert "wechat_unionid" not in doc
    assert doc["wechat_openid"] == "openid_demo"
    assert doc["is_verified"] is True


def test_two_wechat_users_without_unionid_can_register(monkeypatch):
    service, collection = _build_service(monkeypatch)

    first = asyncio.run(service.get_or_create_wechat_user("openid_user_aaaa"))
    second = asyncio.run(service.get_or_create_wechat_user("openid_user_bbbb"))

    assert first is not None and second is not None
    assert first.username != second.username
    assert [doc["wechat_openid"] for doc in collection.docs] == [
        "openid_user_aaaa",
        "openid_user_bbbb",
    ]
    assert all("wechat_unionid" not in doc for doc in collection.docs)


def test_blank_unionid_is_not_written(monkeypatch):
    service, collection = _build_service(monkeypatch)

    user = asyncio.run(service.get_or_create_wechat_user("openid_user_cccc", "  "))

    assert user is not None
    assert "wechat_unionid" not in collection.docs[0]


def test_real_unionid_is_written(monkeypatch):
    service, collection = _build_service(monkeypatch)

    user = asyncio.run(
        service.get_or_create_wechat_user("openid_user_dddd", "union_from_open_platform")
    )

    assert user is not None
    assert collection.docs[0]["wechat_unionid"] == "union_from_open_platform"


def test_existing_wechat_user_can_login_again(monkeypatch):
    service, collection = _build_service(monkeypatch)
    created = asyncio.run(service.get_or_create_wechat_user("openid_user_eeee"))

    again = asyncio.run(service.get_or_create_wechat_user("openid_user_eeee"))

    assert again is not None
    assert again.username == created.username
    assert len(collection.docs) == 1


def test_migrates_sparse_unionid_index_without_touching_null_docs(monkeypatch):
    collection = FakeCollection()
    collection.indexes["wechat_unionid_1"] = {
        "name": "wechat_unionid_1",
        "unique": True,
        "sparse": True,
        "key": "wechat_unionid",
    }
    collection.docs.append(
        {
            "_id": ObjectId(),
            "username": "wx_legacy",
            "wechat_openid": "openid_legacy",
            "wechat_unionid": None,
        }
    )

    _build_service(monkeypatch, collection)

    assert collection.docs[0]["wechat_unionid"] is None
    assert collection.dropped_indexes == ["wechat_unionid_1"]
    spec = collection.indexes["wechat_unionid_1"]
    assert spec["unique"] is True
    assert spec["partialFilterExpression"] == {"wechat_unionid": {"$type": "string"}}


def test_duplicate_key_logs_and_falls_back_to_username(monkeypatch, caplog):
    collection = FakeCollection()
    openid = "abcdefghijklmnop"
    username = f"wx_{openid}"[:50]
    collection.docs.append(
        {
            "_id": ObjectId(),
            "username": username,
            "email": f"{openid}@wechat.local",
            "hashed_password": "hashed",
            "is_active": True,
            "is_verified": True,
            "is_admin": False,
            "wechat_openid": "other-openid",
        }
    )
    collection.insert_one_side_effect = DuplicateKeyError("E11000 duplicate key")
    service, _ = _build_service(monkeypatch, collection)

    with caplog.at_level(logging.WARNING, logger="user_service"):
        user = asyncio.run(service.get_or_create_wechat_user(openid))

    assert user is not None
    assert user.username == username
    assert "唯一键冲突" in caplog.text
    assert openid[:8] in caplog.text
    assert openid not in caplog.text
