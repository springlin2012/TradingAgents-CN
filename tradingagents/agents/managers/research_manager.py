import time

from tradingagents.agents.utils.instrument_utils import build_instrument_context

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger

logger = get_logger("default")

_TRUNCATION_FINISH_REASONS = {"length", "max_tokens"}
_EXCERPT_LIMIT = 400


def _coerce_text(value) -> str:
    """把 LLM 返回的 content / reasoning 字段压成纯文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text).strip())
        return "\n".join(part for part in parts if part)
    return str(value).strip()


def _build_response_excerpt(response, raw_content, limit: int = _EXCERPT_LIMIT):
    """截断时提取原文摘要，优先 content，其次 reasoning_content。"""
    additional = getattr(response, "additional_kwargs", None) if response else None
    if not isinstance(additional, dict):
        additional = {}

    candidates = (
        ("content", raw_content),
        ("reasoning_content", additional.get("reasoning_content")),
        ("reasoning", additional.get("reasoning")),
    )
    for source, value in candidates:
        text = _coerce_text(value)
        if not text:
            continue
        excerpt = text[:limit]
        omitted = max(len(text) - limit, 0)
        suffix = (
            f"...(共{len(text)}字符，已省略{omitted}字符)"
            if omitted
            else f"(共{len(text)}字符)"
        )
        return source, excerpt, suffix
    return "empty", "", "(content与reasoning均为空)"


def _should_log_truncation_excerpt(finish_reason: str, response_length: int, usage: dict) -> bool:
    if finish_reason.lower() in _TRUNCATION_FINISH_REASONS:
        return True
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    try:
        output_tokens = int(output_tokens)
    except (TypeError, ValueError):
        output_tokens = 0
    return response_length <= 10 and output_tokens > 0


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"

        # 安全检查：确保memory不为None
        if memory is not None:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
        else:
            logger.warning("⚠️ [DEBUG] memory为None，跳过历史记忆检索")
            past_memories = []

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""作为投资组合经理和辩论主持人，您的职责是批判性地评估这轮辩论并做出明确决策：支持看跌分析师、看涨分析师，或者仅在基于所提出论点有强有力理由时选择持有。

简洁地总结双方的关键观点，重点关注最有说服力的证据或推理。您的建议——买入、卖出或持有——必须明确且可操作。避免仅仅因为双方都有有效观点就默认选择持有；要基于辩论中最强有力的论点做出承诺。

此外，为交易员制定详细的投资计划。这应该包括：

您的建议：基于最有说服力论点的明确立场。
理由：解释为什么这些论点导致您的结论。
战略行动：实施建议的具体步骤。
📊 目标价格分析：基于所有可用报告（基本面、新闻、情绪），提供全面的目标价格区间和具体价格目标。考虑：
- 基本面报告中的基本估值
- 新闻对价格预期的影响
- 情绪驱动的价格调整
- 技术支撑/阻力位
- 风险调整价格情景（保守、基准、乐观）
- 价格目标的时间范围（1个月、3个月、6个月）
💰 您必须提供具体的目标价格 - 不要回复"无法确定"或"需要更多信息"。

考虑您在类似情况下的过去错误。利用这些见解来完善您的决策制定，确保您在学习和改进。以对话方式呈现您的分析，就像自然说话一样，不使用特殊格式。

以下是您对错误的过去反思：
\"{past_memory_str}\"

标的约束：
{instrument_context}

以下是综合分析报告：
市场研究：{market_research_report}

情绪分析：{sentiment_report}

新闻分析：{news_report}

基本面分析：{fundamentals_report}

以下是辩论：
辩论历史：
{history}

请用中文撰写所有分析内容和建议。"""

        # 📊 统计 prompt 大小
        prompt_length = len(prompt)
        estimated_tokens = int(prompt_length / 1.8)

        logger.info("📊 [Research Manager] Prompt 统计:")
        logger.info(f"   - 辩论历史长度: {len(history)} 字符")
        logger.info(f"   - 总 Prompt 长度: {prompt_length} 字符")
        logger.info(f"   - 估算输入 Token: ~{estimated_tokens} tokens")

        max_retries = 3
        response_content = ""

        for attempt in range(1, max_retries + 1):
            start_time = time.time()
            try:
                logger.info(
                    f"🔄 [Research Manager] 调用LLM生成投资计划 "
                    f"(尝试 {attempt}/{max_retries})"
                )
                response = llm.invoke(prompt)
                elapsed_time = time.time() - start_time

                raw_content = getattr(response, "content", "") if response else ""
                response_content = (
                    raw_content.strip() if isinstance(raw_content, str) else ""
                )
                response_length = len(response_content)
                estimated_output_tokens = int(response_length / 1.8)

                metadata = getattr(response, "response_metadata", {}) or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                raw_usage = (
                    getattr(response, "usage_metadata", None)
                    or metadata.get("token_usage")
                    or {}
                )
                allowed_usage_keys = (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "prompt_tokens",
                    "completion_tokens",
                )
                usage = (
                    {
                        key: raw_usage[key]
                        for key in allowed_usage_keys
                        if key in raw_usage
                    }
                    if isinstance(raw_usage, dict)
                    else {}
                )
                raw_finish_reason = (
                    metadata.get("finish_reason")
                    or metadata.get("stop_reason")
                    or "N/A"
                )
                finish_reason = str(raw_finish_reason)[:50]
                logger.info(f"⏱️ [Research Manager] LLM调用耗时: {elapsed_time:.2f}秒")
                logger.info(
                    f"📊 [Research Manager] 响应统计: {response_length} 字符, "
                    f"估算~{estimated_output_tokens} tokens, "
                    f"finish_reason={finish_reason}, token_usage={usage}"
                )

                if _should_log_truncation_excerpt(finish_reason, response_length, usage):
                    source, excerpt, suffix = _build_response_excerpt(
                        response, raw_content
                    )
                    logger.warning(
                        f"📝 [Research Manager] 截断原文摘要: source={source}, "
                        f"finish_reason={finish_reason}, excerpt={excerpt}{suffix}"
                    )

                if response_length > 10:
                    break

                logger.warning(
                    f"⚠️ [Research Manager] LLM响应为空或过短 "
                    f"(尝试 {attempt}/{max_retries}, 长度={response_length})"
                )
                response_content = ""
            except Exception as exc:
                elapsed_time = time.time() - start_time
                response_content = ""
                logger.error(
                    f"❌ [Research Manager] LLM调用失败 "
                    f"(尝试 {attempt}/{max_retries}, 耗时 {elapsed_time:.2f}秒): {exc}"
                )

        if not response_content:
            raise RuntimeError(
                f"研究经理连续{max_retries}次未返回有效投资计划，分析任务已终止"
            )

        new_investment_debate_state = {
            "judge_decision": response_content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": response_content,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response_content,
        }

    return research_manager_node
