"""指数查询响应模型。不改动个股 ExchangeType。"""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

IndexExchange = Literal["SSE", "SZSE", "BSE", "CSI"]


class IndexCatalogItem(BaseModel):
    id: str
    name: str
    short_name: str
    full_symbol: str
    symbol: str
    exchange: IndexExchange
    publisher: str
    sample_count: Optional[int] = None
    weighting: str
    base_date: str
    aliases: List[str] = Field(default_factory=list)


class IndexQuoteItem(BaseModel):
    id: str
    name: str
    full_symbol: str
    symbol: str
    asset_type: str = "index"
    exchange: IndexExchange
    price: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    amplitude: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    trade_date: Optional[str] = None
    trade_session: Optional[str] = None
    data_source: Optional[str] = None
    updated_at: Optional[str] = None
    available: bool = True
    error: Optional[str] = None


class IndexCatalogData(BaseModel):
    count: int
    items: List[IndexCatalogItem]


class IndexQuoteListData(BaseModel):
    trade_session: str
    timezone: str
    as_of: str
    items: List[IndexQuoteItem]


class IndexApiResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: str = "ok"
    timestamp: str


class IndexCatalogResponse(IndexApiResponse):
    data: IndexCatalogData


class IndexQuoteListResponse(IndexApiResponse):
    data: IndexQuoteListData


class IndexQuoteResponse(IndexApiResponse):
    data: IndexQuoteItem
