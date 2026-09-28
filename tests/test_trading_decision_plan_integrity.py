import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.managers.risk_manager import create_risk_manager
from tradingagents.agents.trader.trader import create_trader
from tradingagents.utils.stock_validator import StockDataPreparer


def _analysis_state(**overrides):
    state = {
        "company_of_interest": "002415",
        "market_report": "市场报告：当前价 10 元，支撑位 9 元，阻力位 12 元。",
        "sentiment_report": "情绪报告：市场情绪中性偏多。",
        "news_report": "新闻报告：近期存在业务催化。",
        "fundamentals_report": "基本面报告：估值合理，盈利保持增长。",
        "investment_plan": "研究经理计划：建议持有并观察突破。",
        "trader_investment_plan": "交易员计划：在 9.5 元附近分批买入。",
        "investment_debate_state": {
            "history": "多空辩论记录",
            "bear_history": "看空观点",
            "bull_history": "看多观点",
            "count": 2,
        },
        "risk_debate_state": {
            "history": "风险辩论记录",
            "risky_history": "激进观点",
            "safe_history": "保守观点",
            "neutral_history": "中性观点",
            "current_risky_response": "激进回应",
            "current_safe_response": "保守回应",
            "current_neutral_response": "中性回应",
            "count": 3,
        },
    }
    state.update(overrides)
    return state


def _response(content, metadata=None, additional_kwargs=None):
    return SimpleNamespace(
        content=content,
        response_metadata=metadata or {},
        additional_kwargs=additional_kwargs or {},
    )


def test_research_manager_retries_empty_responses_until_valid():
    llm = Mock()
    llm.invoke.side_effect = [
        _response("", {"finish_reason": "stop"}),
        _response("   ", {"finish_reason": "stop"}),
        _response("有效的研究经理投资计划，包含建议、依据和目标价格。"),
    ]

    result = create_research_manager(llm, memory=None)(_analysis_state())

    assert result["investment_plan"] == "有效的研究经理投资计划，包含建议、依据和目标价格。"
    assert llm.invoke.call_count == 3


def test_research_manager_raises_after_three_empty_responses():
    llm = Mock()
    llm.invoke.side_effect = [_response(""), _response(" "), None]

    with pytest.raises(RuntimeError, match="研究经理.*有效投资计划"):
        create_research_manager(llm, memory=None)(_analysis_state())

    assert llm.invoke.call_count == 3


def test_research_manager_logs_truncated_reasoning_excerpt(caplog):
    reasoning = "这是一段被截断的思考过程，用于确认日志能留下原文摘要。" * 20
    llm = Mock()
    llm.invoke.return_value = _response(
        "",
        {
            "finish_reason": "length",
            "token_usage": {
                "input_tokens": 7889,
                "output_tokens": 4000,
                "total_tokens": 11889,
            },
        },
        additional_kwargs={"reasoning_content": reasoning},
    )

    with pytest.raises(RuntimeError, match="研究经理.*有效投资计划"):
        create_research_manager(llm, memory=None)(_analysis_state())

    excerpt_logs = [
        record.message
        for record in caplog.records
        if "截断原文摘要" in record.message
    ]
    assert excerpt_logs
    assert "source=reasoning_content" in excerpt_logs[0]
    assert "finish_reason=length" in excerpt_logs[0]
    assert "这是一段被截断的思考过程" in excerpt_logs[0]
    assert "已省略" in excerpt_logs[0]


def test_trader_message_contains_upstream_analysis_reports():
    llm = Mock()
    llm.invoke.return_value = _response("交易员输出：建议持有，目标价 12 元。")
    state = _analysis_state()

    create_trader(llm, memory=None)(state)

    messages = llm.invoke.call_args.args[0]
    user_message = messages[-1]["content"]
    assert state["investment_plan"] in user_message
    assert state["market_report"] in user_message
    assert state["fundamentals_report"] in user_message
    assert state["sentiment_report"] in user_message
    assert state["news_report"] in user_message


def test_risk_manager_prefers_trader_investment_plan():
    llm = Mock()
    llm.invoke.return_value = _response("风险经理输出：接受交易员计划并控制仓位。")
    state = _analysis_state()

    create_risk_manager(llm, memory=None)(state)

    prompt = llm.invoke.call_args.args[0]
    assert state["trader_investment_plan"] in prompt
    assert state["investment_plan"] not in prompt


def test_akshare_financial_sync_does_not_receive_tushare_limit(monkeypatch):
    service = SimpleNamespace(
        sync_historical_data=AsyncMock(
            return_value={"success_count": 1, "total_records": 5}
        ),
        sync_financial_data=AsyncMock(return_value={"success_count": 1}),
        sync_realtime_quotes=AsyncMock(return_value={"success_count": 1}),
    )

    async def get_service():
        return service

    monkeypatch.setattr(
        "app.worker.akshare_sync_service.get_akshare_sync_service", get_service
    )
    preparer = StockDataPreparer.__new__(StockDataPreparer)
    preparer._get_data_source_priority_for_sync = Mock(return_value=["akshare"])

    result = asyncio.run(
        preparer._trigger_data_sync_async(
            "002415", "2026-01-01", "2026-09-23"
        )
    )

    assert result["success"] is True
    service.sync_financial_data.assert_awaited_once_with(symbols=["002415"])
