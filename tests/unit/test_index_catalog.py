import pytest

from app.services.index_catalog import (
    IndexResolveError,
    list_indexes,
    resolve_index_code,
    sanitize_index_amount,
)


def test_catalog_has_six_indexes():
    assert len(list_indexes()) == 6
    assert [spec.id for spec in list_indexes()] == [
        "sse_composite",
        "szse_component",
        "chinext",
        "csi300",
        "star50",
        "bse50",
    ]


@pytest.mark.parametrize(
    "raw",
    ["上证指数", "sse", "sh000001", "000001.SH", "SSE_COMPOSITE"],
)
def test_sse_aliases(raw):
    spec = resolve_index_code(raw)
    assert spec.id == "sse_composite"
    assert spec.full_symbol == "000001.SH"


def test_bare_000001_rejected():
    with pytest.raises(IndexResolveError, match="000001.SH"):
        resolve_index_code("000001")


def test_ping_an_bank_code_rejected():
    with pytest.raises(IndexResolveError, match="平安银行"):
        resolve_index_code("000001.SZ")
    with pytest.raises(IndexResolveError, match="平安银行"):
        resolve_index_code("sz000001")


def test_csi300_dual_code():
    spec = resolve_index_code("399300.SZ")
    assert spec.full_symbol == "000300.SH"
    assert resolve_index_code("399300").id == "csi300"


def test_bse50_requires_bj_prefix():
    spec = resolve_index_code("899050.BJ")
    assert spec.id == "bse50"
    with pytest.raises(IndexResolveError, match="899050.BJ"):
        resolve_index_code("sh899050")
    with pytest.raises(IndexResolveError, match="899050.BJ"):
        resolve_index_code("sz899050")


def test_bare_codes_allowed_except_sse():
    assert resolve_index_code("399001").full_symbol == "399001.SZ"
    assert resolve_index_code("399006").full_symbol == "399006.SZ"
    assert resolve_index_code("000688").full_symbol == "000688.SH"
    assert resolve_index_code("899050").full_symbol == "899050.BJ"


def test_sanitize_index_amount_rejects_wrong_scale():
    yuan = sanitize_index_amount(687009728036.0, "000001.SH")
    assert yuan == pytest.approx(687009728036.0)
    assert sanitize_index_amount(100.0, "000001.SH") is None
