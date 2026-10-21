"""指数行情入库：独立于 QuotesIngestionService，不写 market_quotes。"""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime
from typing import Optional

from pymongo import UpdateOne

from app.core.config import settings
from app.core.database import get_mongo_db
from app.services.data_sources.manager import DataSourceManager
from app.services.index_catalog import all_full_symbols, get_index_by_full_symbol
from app.utils.timezone import get_tz, now_tz

logger = logging.getLogger(__name__)


class IndexQuotesIngestionService:
    def __init__(self) -> None:
        self.tz = get_tz()
        self.manager = DataSourceManager()

    async def ensure_indexes(self) -> None:
        db = get_mongo_db()
        try:
            await db["index_quotes"].create_index("full_symbol", unique=True)
            await db["index_quotes"].create_index("updated_at")
            await db["index_ingestion_status"].create_index("job", unique=True)
        except Exception as e:
            logger.warning(f"创建指数行情索引失败（忽略）: {e}")

    def _is_ingest_window(self, now: Optional[datetime] = None) -> bool:
        now = now or now_tz()
        if now.weekday() > 4:
            return False
        t = now.time()
        return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 30))

    async def run_once(self) -> None:
        if not self._is_ingest_window():
            logger.info("指数行情入库跳过：非交易时段")
            return
        symbols = all_full_symbols()
        quotes, source = self.manager.get_index_quotes_with_fallback(symbols)
        if not quotes:
            await self._record_status("index_quotes_ingestion", False, source, 0, "全部失败")
            return
        db = get_mongo_db()
        now = now_tz()
        ops = []
        for full_symbol, data in quotes.items():
            spec = get_index_by_full_symbol(full_symbol)
            if spec is None:
                continue
            ops.append(
                UpdateOne(
                    {"full_symbol": full_symbol},
                    {
                        "$set": {
                            "full_symbol": full_symbol,
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
                            "data_source": source or data.get("data_source"),
                            "updated_at": now,
                            "data_version": 1,
                        }
                    },
                    upsert=True,
                )
            )
        if ops:
            await db["index_quotes"].bulk_write(ops, ordered=False)
        await self._record_status("index_quotes_ingestion", True, source, len(ops), None)

    async def _record_status(
        self,
        job: str,
        success: bool,
        source: Optional[str],
        records_count: int,
        error_msg: Optional[str],
    ) -> None:
        try:
            db = get_mongo_db()
            await db["index_ingestion_status"].update_one(
                {"job": job},
                {
                    "$set": {
                        "job": job,
                        "success": success,
                        "source": source,
                        "records_count": records_count,
                        "error_message": error_msg,
                        "updated_at": now_tz(),
                        "interval_seconds": settings.INDEX_QUOTES_INGEST_INTERVAL_SECONDS,
                    }
                },
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"记录指数入库状态失败: {e}")
