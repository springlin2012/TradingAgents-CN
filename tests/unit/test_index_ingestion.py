from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.index_quotes_ingestion_service import IndexQuotesIngestionService


TZ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_run_once_skips_weekend():
    svc = IndexQuotesIngestionService()
    saturday = datetime(2026, 10, 17, 10, 0, tzinfo=TZ)
    with patch("app.services.index_quotes_ingestion_service.now_tz", return_value=saturday):
        with patch.object(svc.manager, "get_index_quotes_with_fallback") as fetch:
            await svc.run_once()
            fetch.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_upserts_full_symbol_not_code():
    svc = IndexQuotesIngestionService()
    weekday = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)
    quotes = {
        "000001.SH": {
            "price": 3730.92,
            "open": 3694.12,
            "high": 3743.8,
            "low": 3692.29,
            "prev_close": 3716.28,
            "change": 14.64,
            "change_percent": 0.39,
            "trade_date": "2026-10-19",
        }
    }
    fake_coll = MagicMock()
    fake_coll.bulk_write = AsyncMock()
    fake_status = MagicMock()
    fake_status.update_one = AsyncMock()

    def getter(name):
        if name == "index_quotes":
            return fake_coll
        return fake_status

    fake_db = MagicMock()
    fake_db.__getitem__.side_effect = getter

    with patch("app.services.index_quotes_ingestion_service.now_tz", return_value=weekday):
        with patch.object(svc.manager, "get_index_quotes_with_fallback", return_value=(quotes, "akshare")):
            with patch("app.services.index_quotes_ingestion_service.get_mongo_db", return_value=fake_db):
                await svc.run_once()

    fake_coll.bulk_write.assert_awaited()
    ops = fake_coll.bulk_write.await_args.args[0]
    assert ops[0]._filter == {"full_symbol": "000001.SH"}
    assert "code" not in ops[0]._filter
    names = [call.args[0] for call in fake_db.__getitem__.call_args_list]
    assert "market_quotes" not in names
