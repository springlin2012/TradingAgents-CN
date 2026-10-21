"""A 股宽基指数查询 API。路径前缀 /indexes，main.py 再挂 /api。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.response import ok
from app.models.index_models import (
    IndexCatalogResponse,
    IndexQuoteListResponse,
    IndexQuoteResponse,
)
from app.routers.auth_db import get_current_user
from app.services.index_catalog import IndexResolveError
from app.services.index_data_service import (
    IndexDataService,
    IndexQuoteNotFound,
    IndexQuotesTimeout,
    IndexQuotesUnavailable,
)

router = APIRouter(prefix="/indexes", tags=["indexes"])
_service = IndexDataService()

_CODE_DESC = (
    "指数代码：000001.SH / sh000001 / 上证指数 / sse。"
    "裸 000001 会 400（与平安银行冲突）。"
)


def _split_codes(codes: Optional[str]):
    if not codes:
        return None
    items = [item.strip() for item in codes.split(",") if item.strip()]
    return items or None


@router.get(
    "",
    summary="指数目录",
    response_model=IndexCatalogResponse,
    responses={401: {"description": "未登录"}},
)
@router.get("/", include_in_schema=False)
async def list_indexes(current_user: dict = Depends(get_current_user)):
    """返回 v1 覆盖的 6 只宽基指数元数据，不含行情。"""
    return ok(data=_service.get_catalog())


@router.get(
    "/quotes",
    summary="批量最新行情",
    response_model=IndexQuoteListResponse,
    responses={
        400: {"description": "代码无法解析，例如裸 000001"},
        401: {"description": "未登录"},
        502: {"description": "6 只全部失败且无缓存"},
        504: {"description": "外部源超时"},
    },
)
async def list_index_quotes(
    codes: Optional[str] = Query(
        None,
        description="逗号分隔；空=全部 6 只。例：000001.SH,399001.SZ",
        example="000001.SH,399001.SZ",
    ),
    force_refresh: bool = Query(False, description="跳过 Mongo 缓存，强制拉 AKShare"),
    current_user: dict = Depends(get_current_user),
):
    """批量最新点位。单只失败该项 available=false，其余照常返回。数据源仅 AKShare。"""
    try:
        data = await _service.get_quotes(_split_codes(codes), force_refresh=force_refresh)
        return ok(data=data)
    except IndexResolveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IndexQuotesTimeout as e:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e))
    except IndexQuotesUnavailable as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get(
    "/{code}/quote",
    summary="单只最新行情",
    response_model=IndexQuoteResponse,
    responses={
        400: {"description": "代码无法解析，例如裸 000001"},
        401: {"description": "未登录"},
        404: {"description": "已解析但无行情"},
        504: {"description": "外部源超时"},
    },
)
async def get_index_quote(
    code: str = Path(..., description=_CODE_DESC, example="000001.SH"),
    force_refresh: bool = Query(False, description="跳过 Mongo 缓存，强制拉 AKShare"),
    current_user: dict = Depends(get_current_user),
):
    """单只最新行情。不提供 K 线。数据源仅 AKShare。"""
    try:
        data = await _service.get_quote(code, force_refresh=force_refresh)
        return ok(data=data)
    except IndexResolveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IndexQuotesTimeout as e:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e))
    except IndexQuoteNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该指数行情")
