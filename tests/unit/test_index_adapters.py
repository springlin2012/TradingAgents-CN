from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.data_sources.akshare_adapter import AKShareAdapter
from app.services.data_sources.manager import DataSourceManager
from app.services.data_sources.tushare_adapter import TushareAdapter


def test_akshare_index_quotes_does_not_call_stock_spot():
    adapter = AKShareAdapter()
    spot = pd.DataFrame([{
        "代码": "sh000001",
        "最新价": 3730.92,
        "今开": 3694.12,
        "最高": 3743.8,
        "最低": 3692.29,
        "昨收": 3716.28,
        "涨跌额": 14.64,
        "涨跌幅": 0.39,
        "成交量": 417791248,
        "成交额": 687009728036.0,
    }])
    fake_ak = MagicMock()
    fake_ak.stock_zh_index_spot_em.return_value = spot
    with patch.dict("sys.modules", {"akshare": fake_ak}):
        adapter.is_available = lambda: True
        result = adapter.get_index_quotes(["000001.SH"])
    fake_ak.stock_zh_a_spot_em.assert_not_called()
    fake_ak.stock_zh_a_hist.assert_not_called()
    fake_ak.stock_zh_index_daily.assert_not_called()
    assert result["000001.SH"]["price"] == 3730.92


def test_akshare_index_quotes_falls_back_to_tencent_daily():
    adapter = AKShareAdapter()
    daily = pd.DataFrame([
        {"date": "2026-10-20", "open": 1, "high": 2, "low": 0.5, "close": 1.4, "volume": 10},
        {"date": "2026-10-21", "open": 1.4, "high": 2, "low": 1, "close": 1.5, "volume": 20},
    ])
    fake_ak = MagicMock()
    fake_ak.stock_zh_index_spot_em.side_effect = Exception("ProxyError('Unable to connect to proxy')")
    fake_ak.stock_zh_index_daily.return_value = daily
    with patch.dict("sys.modules", {"akshare": fake_ak}):
        adapter.is_available = lambda: True
        with patch.object(adapter, "_call_akshare", side_effect=lambda fn, label: fn()):
            result = adapter.get_index_quotes(["000001.SH"])
    fake_ak.stock_zh_index_daily.assert_called()
    assert result["000001.SH"]["price"] == 1.5
    assert result["000001.SH"]["prev_close"] == 1.4


def test_manager_index_quotes_only_uses_akshare():
    manager = DataSourceManager()
    ak = MagicMock()
    ak.name = "akshare"
    ak.get_index_quotes.return_value = {
        "000001.SH": {"price": 3730.92, "amount": 687009728036.0}
    }
    ts = MagicMock()
    ts.name = "tushare"
    ts.get_index_quotes.return_value = {"000001.SH": {"price": 1}}
    manager.get_available_adapters = lambda: [ak, ts]

    data, source = manager.get_index_quotes_with_fallback(["000001.SH"])
    assert source == "akshare"
    assert data["000001.SH"]["price"] == 3730.92
    ak.get_index_quotes.assert_called_once()
    ts.get_index_quotes.assert_not_called()


def test_tushare_adapter_does_not_override_index_quotes():
    assert "get_index_quotes" not in TushareAdapter.__dict__
    assert "get_index_kline" not in TushareAdapter.__dict__
    adapter = TushareAdapter()
    assert adapter.get_index_quotes(["000001.SH"]) is None
