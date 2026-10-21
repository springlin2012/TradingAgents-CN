from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import indexes as indexes_router
from app.routers.auth_db import get_current_user
from app.services.index_data_service import IndexQuotesUnavailable


def create_test_app():
    app = FastAPI()
    app.include_router(indexes_router.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test",
        "username": "test",
        "is_admin": True,
        "roles": ["admin"],
    }
    return app


@pytest.fixture()
def client():
    app = create_test_app()
    with TestClient(app) as c:
        yield c


def test_catalog_count_six(client):
    resp = client.get("/api/indexes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["count"] == 6


def test_bare_000001_returns_400(client):
    resp = client.get("/api/indexes/000001/quote")
    assert resp.status_code == 400
    assert "000001.SH" in resp.json()["detail"]


def test_csi300_alias_normalized(client):
    quote = {
        "id": "csi300",
        "name": "沪深300指数",
        "full_symbol": "000300.SH",
        "available": True,
    }
    with patch.object(indexes_router._service, "get_quote", new=AsyncMock(return_value=quote)):
        resp = client.get("/api/indexes/399300.SZ/quote")
    assert resp.status_code == 200
    assert resp.json()["data"]["full_symbol"] == "000300.SH"


def test_batch_partial_failure_still_200(client):
    data = {
        "trade_session": "closed",
        "timezone": "Asia/Shanghai",
        "as_of": "2026-10-21T15:00:00+08:00",
        "items": [
            {"id": "sse_composite", "available": True, "full_symbol": "000001.SH"},
            {"id": "star50", "available": False, "full_symbol": "000688.SH", "error": "timeout"},
        ],
    }
    with patch.object(indexes_router._service, "get_quotes", new=AsyncMock(return_value=data)):
        resp = client.get("/api/indexes/quotes")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert any(item["available"] is False for item in items)


def test_batch_all_failed_returns_502(client):
    with patch.object(
        indexes_router._service,
        "get_quotes",
        new=AsyncMock(side_effect=IndexQuotesUnavailable("全部指数行情获取失败")),
    ):
        resp = client.get("/api/indexes/quotes")
    assert resp.status_code == 502


def test_kline_endpoint_removed(client):
    resp = client.get("/api/indexes/000001.SH/kline")
    assert resp.status_code == 404


def test_index_path_does_not_write_market_quotes(client):
    quote = {
        "id": "szse_component",
        "full_symbol": "399001.SZ",
        "available": True,
    }
    with patch("app.services.index_data_service.get_mongo_db") as mongo:
        with patch.object(indexes_router._service, "get_quote", new=AsyncMock(return_value=quote)):
            resp = client.get("/api/indexes/399001/quote")
        mongo.return_value.__getitem__.assert_not_called()
    assert resp.status_code == 200
