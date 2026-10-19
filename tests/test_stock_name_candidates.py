"""名称候选搜索：使用隔离的真实 MongoDB 验证聚合与接口契约。"""

import asyncio
import os
import re
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.uri_parser import parse_uri

# 避免导入认证模块时初始化业务数据库的旧配置存储，随后恢复环境。
with patch.dict(os.environ, {"USE_MONGODB_STORAGE": "false"}):
    from app.core.config import settings
    from app.core import database, unified_config
    from app.routers import stock_data
    from app.services import stock_data_service


class AsyncCursor:
    """仅适配同步驱动协议；查询、排序与聚合均由真实 MongoDB 执行。"""

    def __init__(self, cursor):
        self.cursor = cursor

    def limit(self, value):
        self.cursor = self.cursor.limit(value)
        return self

    async def to_list(self, length):
        return list(self.cursor) if length is None else [
            doc for _, doc in zip(range(length), self.cursor)
        ]


class AsyncCollection:
    def __init__(self, collection):
        self.collection = collection
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return AsyncCursor(self.collection.aggregate(pipeline))

    def find(self, *args, **kwargs):
        return AsyncCursor(self.collection.find(*args, **kwargs))


class AsyncDatabase(SimpleNamespace):
    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def candidate_db(monkeypatch):
    uri = os.getenv("TEST_STOCK_CANDIDATES_MONGO_URI", settings.MONGO_URI)
    if not os.getenv("TEST_STOCK_CANDIDATES_MONGO_URI"):
        if any(host not in ("localhost", "127.0.0.1", "::1")
               for host, _ in parse_uri(uri)["nodelist"]):
            pytest.skip("真实聚合测试仅自动连接本机 MongoDB")
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip("真实聚合测试需要本机 MongoDB 或显式测试连接")
    db_name = "test_stock_candidates_" + uuid4().hex
    created_db_name = db_name
    db = client[db_name]
    adapter = AsyncCollection(db.stock_basic_info)
    async_db = AsyncDatabase(stock_basic_info=adapter)
    monkeypatch.setattr(stock_data_service, "get_mongo_db", lambda: async_db)
    monkeypatch.setattr(database, "get_mongo_db", lambda: async_db)
    try:
        yield db.stock_basic_info, adapter
    finally:
        # 唯一随机数据库由本测试创建，禁止清理任何业务数据库。
        assert db_name == created_db_name
        assert re.fullmatch(r"test_stock_candidates_[0-9a-f]{32}", db_name)
        client.drop_database(db_name)
        assert db_name not in client.list_database_names()
        client.close()


@pytest.fixture
def api_client(monkeypatch):
    async def sources(self):
        return [SimpleNamespace(type="tushare", enabled=True)]

    monkeypatch.setattr(
        unified_config.UnifiedConfigManager, "get_data_source_configs_async", sources
    )
    app = FastAPI()
    app.include_router(stock_data.router)
    app.dependency_overrides[stock_data.get_current_user] = lambda: {"id": "test"}
    with TestClient(app) as client:
        yield client


def search(keyword, limit=10):
    return asyncio.run(
        stock_data_service.StockDataService().search_stock_candidates(keyword, limit)
    )


@pytest.mark.parametrize("keyword", ["*", ".", "[", "+", "(", "\\", "$", "海[+]"])
def test_literal_name_substrings(candidate_db, keyword):
    collection, _ = candidate_db
    collection.insert_many([
        {"symbol": "600001", "name": "甲" + keyword + "乙", "source": "tushare"},
        {"symbol": "600002", "name": "普通公司", "source": "tushare"},
    ])
    assert search(keyword) == [
        {"symbol": "600001", "name": "甲" + keyword + "乙", "source": "tushare"}
    ]


def test_exact_prefix_contains_and_code_order(candidate_db):
    collection, _ = candidate_db
    collection.insert_many([
        {"symbol": "600003", "name": "东方海", "source": "tushare"},
        {"symbol": "600005", "name": "海天", "source": "tushare"},
        {"symbol": "600002", "name": "海", "source": "tushare"},
        {"symbol": "600004", "name": "海润", "source": "tushare"},
        {"symbol": "600001", "name": "中海", "source": "tushare"},
    ])
    assert [row["symbol"] for row in search("海")] == [
        "600002", "600004", "600005", "600001", "600003"
    ]


def test_source_priority_fallback_and_deduplication(candidate_db):
    collection, _ = candidate_db
    sources = ["baostock", "akshare", "multi_source", "tushare"]
    collection.insert_many([
        {"symbol": "600001", "name": "海" + source, "source": source}
        for source in sources
    ] + [
        {"code": "600002", "name": "海二", "source": "akshare"},
        {"code": "600002", "name": "海二优先", "source": "multi_source"},
        {"code": "600003", "name": "海三", "source": "baostock"},
        {"code": "600004", "name": "海四", "source": "custom"},
        {"code": "600005", "name": "海五"},
    ])
    assert [(row["symbol"], row["source"]) for row in search("海")] == [
        ("600001", "tushare"), ("600002", "multi_source"),
        ("600003", "baostock"), ("600004", "custom"), ("600005", "unknown")
    ]


def test_code_compatibility_fields_and_a_share_scope(candidate_db):
    collection, _ = candidate_db
    collection.insert_many([
        {"code": 1, "name": "海一", "source": "akshare"},
        {"symbol": "", "code": "2", "name": "海二"},
        {"symbol": "600001", "code": "600002", "name": "海三", "source": "tushare"},
        {"symbol": "00700", "name": "海港股", "market": "HK"},
        {"symbol": "AAPL", "name": "海美股", "market": "US"},
        {"symbol": "bad", "name": "海坏数据"},
        {"symbol": "1234567", "name": "海超长代码"},
        {"name": "海无代码"},
    ])
    assert search("海") == [
        {"symbol": "000001", "name": "海一", "source": "akshare"},
        {"symbol": "000002", "name": "海二", "source": "unknown"},
        {"symbol": "600001", "name": "海三", "source": "tushare"},
    ]


def test_updated_at_and_id_stable_source_tiebreak(candidate_db):
    collection, _ = candidate_db
    collection.insert_many([
        {"_id": "a", "symbol": "600001", "name": "海旧", "source": "tushare",
         "updated_at": datetime(2026, 1, 1)},
        {"_id": "b", "symbol": "600001", "name": "海新一", "source": "tushare",
         "updated_at": "2026-02-01T00:00:00Z"},
        {"_id": "c", "symbol": "600001", "name": "海新二", "source": "tushare",
         "updated_at": datetime(2026, 2, 1)},
    ])
    assert search("海")[0]["name"] == "海新二"
    assert search("海") == search("海")


def test_limit_is_applied_after_deduplication_and_capped(candidate_db):
    collection, adapter = candidate_db
    collection.insert_many([
        {"symbol": f"600{i:03}", "name": "海" + str(i), "source": source}
        for i in range(15) for source in ("tushare", "akshare")
    ])
    assert len(search("海", 50)) == 10
    assert len(search("海", 3)) == 3
    assert {"$limit": 3} in adapter.pipelines[-1]
    assert len({row["symbol"] for row in search("海")}) == 10


def test_autocomplete_contract_and_trim(api_client, candidate_db):
    collection, _ = candidate_db
    collection.insert_one({"code": "600001", "name": "海天", "source": "akshare"})
    response = api_client.get("/api/stock-data/search", params={
        "keyword": " 海 ", "mode": "autocomplete",
    })
    assert response.status_code == 200
    assert response.json() == {
        "success": True, "data": [{"symbol": "600001", "name": "海天", "source": "akshare"}],
        "total": 1, "keyword": "海", "source": "mixed", "message": "搜索完成"
    }


def test_autocomplete_endpoint_caps_limit(api_client, candidate_db):
    collection, _ = candidate_db
    collection.insert_many([
        {"symbol": f"600{i:03}", "name": "海" + str(i), "source": "tushare"}
        for i in range(15)
    ])
    response = api_client.get("/api/stock-data/search", params={
        "keyword": "海", "mode": "autocomplete", "limit": 50,
    })
    assert response.status_code == 200
    assert response.json()["total"] == 10
    assert len(response.json()["data"]) == 10


@pytest.mark.parametrize("keyword", [" ", "\t\n", "海" * 51])
def test_autocomplete_keyword_validation(api_client, keyword):
    response = api_client.get("/api/stock-data/search", params={
        "keyword": keyword, "mode": "autocomplete",
    })
    assert response.status_code == 422


def test_autocomplete_allows_fifty_trimmed_characters(api_client, candidate_db):
    response = api_client.get("/api/stock-data/search", params={
        "keyword": " " + "海" * 50 + " ", "mode": "autocomplete",
    })
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_default_search_contract_is_preserved(api_client, candidate_db):
    collection, _ = candidate_db
    collection.insert_many([
        {"symbol": "600001", "name": "海天", "source": "tushare", "industry": "食品"},
        {"symbol": "600002", "name": "海润", "source": "akshare"},
    ])
    response = api_client.get("/api/stock-data/search", params={"keyword": "海", "limit": 50})
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tushare"
    assert payload["total"] == 1
    assert payload["data"][0]["industry"] == "食品"


def test_invalid_mode_and_limit(api_client):
    for params in ({"mode": "bad"}, {"mode": "autocomplete", "limit": 0}, {"limit": 51}):
        response = api_client.get("/api/stock-data/search", params={"keyword": "海", **params})
        assert response.status_code == 422


def test_autocomplete_http_exception_status_is_preserved(api_client, monkeypatch):
    async def denied(*args):
        raise HTTPException(status_code=503, detail="暂不可用")

    monkeypatch.setattr(
        stock_data_service.StockDataService, "search_stock_candidates", denied, raising=False
    )
    response = api_client.get("/api/stock-data/search", params={
        "keyword": "海", "mode": "autocomplete",
    })
    assert response.status_code == 503


def test_search_requires_authentication():
    app = FastAPI()
    app.include_router(stock_data.router)
    with TestClient(app) as client:
        for mode in ("default", "autocomplete"):
            response = client.get("/api/stock-data/search", params={"keyword": "海", "mode": mode})
            assert response.status_code == 401
