"""A 股 6 只宽基指数目录：别名解析与代码转换。

禁止把裸 000001 当上证指数，禁止走 Tushare `_normalize_ts_code`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

IndexExchange = str  # SSE / SZSE / BSE / CSI


class IndexResolveError(ValueError):
    """指数代码无法解析为目录内标的。"""


@dataclass(frozen=True)
class IndexSpec:
    id: str
    name: str
    short_name: str
    full_symbol: str
    symbol: str
    exchange: IndexExchange
    publisher: str
    aliases: Tuple[str, ...]
    sample_count: Optional[int]
    weighting: str
    base_date: str

    @property
    def akshare_symbol(self) -> str:
        prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj", "CSI": "sh"}[self.exchange]
        return f"{prefix}{self.symbol}"

    @property
    def baostock_code(self) -> Optional[str]:
        if self.exchange == "BSE":
            return None
        prefix = "sz" if self.exchange == "SZSE" else "sh"
        return f"{prefix}.{self.symbol}"


INDEXES: Tuple[IndexSpec, ...] = (
    IndexSpec(
        id="sse_composite",
        name="上证综合指数",
        short_name="上证指数",
        full_symbol="000001.SH",
        symbol="000001",
        exchange="SSE",
        publisher="上海证券交易所",
        aliases=(
            "上证指数",
            "上证综指",
            "上证",
            "sse",
            "sse_composite",
            "sh000001",
            "000001.sh",
        ),
        sample_count=None,
        weighting="total_shares",
        base_date="1990-12-19",
    ),
    IndexSpec(
        id="szse_component",
        name="深证成份指数",
        short_name="深证成指",
        full_symbol="399001.SZ",
        symbol="399001",
        exchange="SZSE",
        publisher="深圳证券交易所",
        aliases=(
            "深证指数",
            "深证成指",
            "深成指",
            "szse",
            "szse_component",
            "sz399001",
            "399001.sz",
            "399001",
        ),
        sample_count=500,
        weighting="free_float",
        base_date="1995-01-23",
    ),
    IndexSpec(
        id="chinext",
        name="创业板指数",
        short_name="创业板指",
        full_symbol="399006.SZ",
        symbol="399006",
        exchange="SZSE",
        publisher="深圳证券交易所",
        aliases=(
            "创业板指数",
            "创业板指",
            "创业板",
            "chinext",
            "sz399006",
            "399006.sz",
            "399006",
        ),
        sample_count=100,
        weighting="free_float",
        base_date="2010-06-01",
    ),
    IndexSpec(
        id="csi300",
        name="沪深300指数",
        short_name="沪深300",
        full_symbol="000300.SH",
        symbol="000300",
        exchange="CSI",
        publisher="中证指数有限公司",
        aliases=(
            "沪深300",
            "沪深300指数",
            "hs300",
            "csi300",
            "sh000300",
            "000300.sh",
            "000300",
            "399300",
            "399300.sz",
            "sz399300",
        ),
        sample_count=300,
        weighting="free_float",
        base_date="2005-04-08",
    ),
    IndexSpec(
        id="star50",
        name="上证科创板50成份指数",
        short_name="科创50",
        full_symbol="000688.SH",
        symbol="000688",
        exchange="SSE",
        publisher="上海证券交易所",
        aliases=(
            "科创50",
            "kcb50",
            "star50",
            "sh000688",
            "000688.sh",
            "000688",
        ),
        sample_count=50,
        weighting="free_float",
        base_date="2020-07-22",
    ),
    IndexSpec(
        id="bse50",
        name="北证50成份指数",
        short_name="北证50",
        full_symbol="899050.BJ",
        symbol="899050",
        exchange="BSE",
        publisher="北京证券交易所",
        aliases=(
            "北证50",
            "bj50",
            "bse50",
            "bj899050",
            "899050.bj",
            "899050",
        ),
        sample_count=50,
        weighting="free_float",
        base_date="2022-11-21",
    ),
)

_BARE_ALLOWED = {"399001", "399006", "000300", "000688", "899050", "399300"}
_PREFIX_RE = re.compile(r"^(sh|sz|bj)(\d{6})$", re.IGNORECASE)
_DOT_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$", re.IGNORECASE)


def _normalize_raw(raw: str) -> str:
    text = (raw or "").strip()
    text = text.replace("．", ".").replace("。", ".")
    text = "".join(text.split())
    return text


def _build_alias_map() -> Dict[str, IndexSpec]:
    mapping: Dict[str, IndexSpec] = {}
    for spec in INDEXES:
        keys = {
            spec.id,
            spec.name,
            spec.short_name,
            spec.full_symbol,
            spec.full_symbol.lower(),
            spec.akshare_symbol,
            spec.akshare_symbol.lower(),
        }
        keys.update(spec.aliases)
        for key in keys:
            mapping[key.lower()] = spec
    return mapping


_ALIAS_MAP = _build_alias_map()
_BY_FULL = {spec.full_symbol: spec for spec in INDEXES}
_BY_ID = {spec.id: spec for spec in INDEXES}


def list_indexes() -> List[IndexSpec]:
    return list(INDEXES)


def all_full_symbols() -> List[str]:
    return [spec.full_symbol for spec in INDEXES]


def get_index_by_full_symbol(full_symbol: str) -> Optional[IndexSpec]:
    return _BY_FULL.get(full_symbol)


def resolve_index_code(raw: str) -> IndexSpec:
    text = _normalize_raw(raw)
    if not text:
        raise IndexResolveError("指数代码不能为空")

    lower = text.lower()
    if lower in {"000001", "1"}:
        raise IndexResolveError("上证指数请使用 000001.SH")

    if lower in {"000001.sz", "sz000001"}:
        raise IndexResolveError("000001.SZ 是平安银行，上证指数请使用 000001.SH")

    if lower in {"sh899050", "sz899050", "899050.sh", "899050.sz"}:
        raise IndexResolveError("北证50请使用 899050.BJ")

    aliased = _ALIAS_MAP.get(lower)
    if aliased:
        return aliased

    prefix_match = _PREFIX_RE.match(text)
    if prefix_match:
        market, code6 = prefix_match.group(1).lower(), prefix_match.group(2)
        if market in {"sh", "sz"} and code6 == "899050":
            raise IndexResolveError("北证50请使用 899050.BJ")
        if market == "sz" and code6 == "000001":
            raise IndexResolveError("000001.SZ 是平安银行，上证指数请使用 000001.SH")
        full_symbol = {
            "sh": f"{code6}.SH",
            "sz": f"{code6}.SZ",
            "bj": f"{code6}.BJ",
        }[market]
        if full_symbol == "399300.SZ":
            return _BY_ID["csi300"]
        spec = _BY_FULL.get(full_symbol)
        if spec:
            return spec
        raise IndexResolveError(f"未支持的指数代码: {text}")

    dot_match = _DOT_RE.match(text)
    if dot_match:
        code6, market = dot_match.group(1), dot_match.group(2).upper()
        if market in {"SH", "SZ"} and code6 == "899050":
            raise IndexResolveError("北证50请使用 899050.BJ")
        if market == "SZ" and code6 == "000001":
            raise IndexResolveError("000001.SZ 是平安银行，上证指数请使用 000001.SH")
        full_symbol = f"{code6}.{market}"
        if full_symbol == "399300.SZ":
            return _BY_ID["csi300"]
        spec = _BY_FULL.get(full_symbol)
        if spec:
            return spec
        raise IndexResolveError(f"未支持的指数代码: {text}")

    if text.isdigit() and len(text) <= 6:
        code6 = text.zfill(6)
        if code6 == "000001":
            raise IndexResolveError("上证指数请使用 000001.SH")
        if code6 == "399300":
            return _BY_ID["csi300"]
        if code6 in _BARE_ALLOWED:
            for spec in INDEXES:
                if spec.symbol == code6:
                    return spec
        raise IndexResolveError(f"未支持的指数代码: {text}")

    raise IndexResolveError(f"未支持的指数代码: {text}")


def sanitize_index_amount(amount, full_symbol: str):
    if amount is None:
        return None
    try:
        yuan = float(amount)
    except (TypeError, ValueError):
        return None
    if full_symbol == "000001.SH" and (yuan < 1e10 or yuan > 1e14):
        return None
    return yuan
