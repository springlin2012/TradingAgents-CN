"""指数行情编排：独立集合 + AKShare 降级。不提供 K 线。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional

from app.core.database import get_mongo_db
from app.services.data_sources.manager import DataSourceManager
from app.services.index_catalog import (
    IndexSpec,
    list_indexes,
    resolve_index_code,
)
from app.utils.timezone import get_tz, now_tz

logger = logging.getLogger(__name__)

EXTERNAL_TIMEOUT = 30.0


def get_trade_session(now: Optional[datetime] = None) -> str:
    """v1 仅工作日 + 时点，不做交易所日历。周末为 holiday。"""
    now = now or now_tz()
    if now.tzinfo is None:
        now = now.replace(tzinfo=get_tz())
    if now.weekday() > 4:
        return "holiday"
    t = now.time()
    if t < dtime(9, 30):
        return "pre_market"
    if dtime(9, 30) <= t <= dtime(11, 30):
        return "trading"
    if dtime(11, 30) < t < dtime(13, 0):
        return "lunch"
    if dtime(13, 0) <= t <= dtime(15, 0):
        return "trading"
    return "closed"


def _format_dt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class IndexDataService:
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or DataSourceManager()

    def get_catalog(self) -> Dict[str, Any]:
        items = []
        for spec in list_indexes():
            items.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "short_name": spec.short_name,
                    "full_symbol": spec.full_symbol,
                    "symbol": spec.symbol,
                    "exchange": spec.exchange,
                    "publisher": spec.publisher,
                    "sample_count": spec.sample_count,
                    "weighting": spec.weighting,
                    "base_date": spec.base_date,
                    "aliases": list(spec.aliases),
                }
            )
        return {"count": len(items), "items": items}

    async def get_quotes(
        self, raw_codes: Optional[List[str]] = None, force_refresh: bool = False
    ) -> Dict[str, Any]:
        if raw_codes:
            specs = [resolve_index_code(code) for code in raw_codes]
        else:
            specs = list_indexes()

        session = get_trade_session()
        cached_by_symbol: Dict[str, Dict[str, Any]] = {}
        missing: List[IndexSpec] = []
        for spec in specs:
            cached = None if force_refresh else await self._read_quote(spec.full_symbol)
            if cached:
                cached_by_symbol[spec.full_symbol] = cached
            else:
                missing.append(spec)

        fetched: Dict[str, Dict[str, Any]] = {}
        source = None
        if missing:
            try:
                quotes, source = await self._fetch_quotes_external(
                    [spec.full_symbol for spec in missing]
                )
                fetched = quotes or {}
            except IndexQuotesTimeout:
                raise
            except Exception as e:
                logger.warning(f"batch index quotes failed: {e}")

        items = []
        for spec in specs:
            try:
                if spec.full_symbol in cached_by_symbol:
                    items.append(
                        self._quote_from_doc(
                            spec,
                            cached_by_symbol[spec.full_symbol],
                            session,
                            cached_by_symbol[spec.full_symbol].get("data_source") or "mongodb",
                        )
                    )
                    continue
                data = fetched.get(spec.full_symbol)
                if not data:
                    items.append(self._unavailable(spec, "未找到行情", session))
                    continue
                doc = await self._write_quote(spec, data, source or data.get("data_source") or "unknown")
                items.append(self._quote_from_doc(spec, doc, session, source or "unknown"))
            except Exception as e:
                logger.warning(f"index quote failed for {spec.full_symbol}: {e}")
                items.append(self._unavailable(spec, str(e), session))

        available = [item for item in items if item.get("available")]
        if not available:
            raise IndexQuotesUnavailable("全部指数行情获取失败")

        as_of = next((item.get("updated_at") for item in available if item.get("updated_at")), now_tz().isoformat())
        return {
            "trade_session": session,
            "timezone": str(get_tz()),
            "as_of": as_of,
            "items": items,
        }

    async def get_quote(self, raw_code: str, force_refresh: bool = False) -> Dict[str, Any]:
        spec = resolve_index_code(raw_code)
        quote = await self._load_quote(spec, force_refresh=force_refresh)
        if not quote.get("available"):
            raise IndexQuoteNotFound(spec.full_symbol)
        return quote

    async def _load_quote(self, spec: IndexSpec, force_refresh: bool) -> Dict[str, Any]:
        session = get_trade_session()
        cached = None if force_refresh else await self._read_quote(spec.full_symbol)
        if cached:
            return self._quote_from_doc(spec, cached, session, cached.get("data_source") or "mongodb")

        quotes, source = await self._fetch_quotes_external([spec.full_symbol])
        data = (quotes or {}).get(spec.full_symbol)
        if not data:
            if cached:
                return self._quote_from_doc(spec, cached, session, cached.get("data_source") or "mongodb")
            return self._unavailable(spec, "未找到行情", session)

        doc = await self._write_quote(spec, data, source or "unknown")
        return self._quote_from_doc(spec, doc, session, source or "unknown")

    async def _fetch_quotes_external(self, full_symbols: List[str]):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.manager.get_index_quotes_with_fallback, full_symbols),
                timeout=EXTERNAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise IndexQuotesTimeout("获取指数行情超时，请稍后重试")

    async def _read_quote(self, full_symbol: str) -> Optional[Dict[str, Any]]:
        db = get_mongo_db()
        return await db["index_quotes"].find_one({"full_symbol": full_symbol}, {"_id": 0})

    async def _write_quote(self, spec: IndexSpec, data: Dict[str, Any], source: str) -> Dict[str, Any]:
        db = get_mongo_db()
        now = now_tz()
        doc = {
            "full_symbol": spec.full_symbol,
            "symbol": spec.symbol,
            "id": spec.id,
            "name": spec.name,
            "price": data.get("price"),
            "open": data.get("open"),
            "high": data.get("high"),
            "low": data.get("low"),
            "prev_close": data.get("prev_close"),
            "change": data.get("change"),
            "change_percent": data.get("change_percent"),
            "amplitude": data.get("amplitude"),
            "volume": data.get("volume"),
            "amount": data.get("amount"),
            "turnover_rate": data.get("turnover_rate"),
            "pe": data.get("pe"),
            "pb": data.get("pb"),
            "trade_date": data.get("trade_date"),
            "data_source": source,
            "updated_at": now,
            "data_version": 1,
        }
        await db["index_quotes"].update_one(
            {"full_symbol": spec.full_symbol},
            {"$set": doc},
            upsert=True,
        )
        return doc

    def _quote_from_doc(
        self, spec: IndexSpec, doc: Dict[str, Any], session: str, source: str
    ) -> Dict[str, Any]:
        return {
            "id": spec.id,
            "name": spec.name,
            "full_symbol": spec.full_symbol,
            "symbol": spec.symbol,
            "asset_type": "index",
            "exchange": spec.exchange,
            "price": doc.get("price"),
            "open": doc.get("open"),
            "high": doc.get("high"),
            "low": doc.get("low"),
            "prev_close": doc.get("prev_close"),
            "change": doc.get("change"),
            "change_percent": doc.get("change_percent"),
            "amplitude": doc.get("amplitude"),
            "volume": doc.get("volume"),
            "amount": doc.get("amount"),
            "turnover_rate": doc.get("turnover_rate"),
            "pe": doc.get("pe"),
            "pb": doc.get("pb"),
            "trade_date": doc.get("trade_date"),
            "trade_session": session,
            "data_source": source,
            "updated_at": _format_dt(doc.get("updated_at")),
            "available": True,
        }

    def _unavailable(self, spec: IndexSpec, error: str, session: str) -> Dict[str, Any]:
        return {
            "id": spec.id,
            "name": spec.name,
            "full_symbol": spec.full_symbol,
            "symbol": spec.symbol,
            "asset_type": "index",
            "exchange": spec.exchange,
            "trade_session": session,
            "available": False,
            "error": error,
        }


class IndexQuoteNotFound(Exception):
    pass


class IndexQuotesUnavailable(Exception):
    pass


class IndexQuotesTimeout(Exception):
    pass
