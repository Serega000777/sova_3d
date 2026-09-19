"""Claude planner (AI_PROVIDER=anthropic).

Structured output via `client.messages.parse(output_format=PlannerOutput)`;
the stable system prompt carries a cache breakpoint so repeated planning
calls only pay for the request. Model and effort are settings; usage is
turned into USD with the public per-token rates for the usage ledger.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Literal, cast

import anthropic
from anthropic.types import ContentBlockParam, OutputConfigParam

from app.ai.contract import (
    PlannerOutput,
    PlannerResult,
    PlanRequest,
    Usage,
    system_prompt,
    user_content,
)

PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5"
MAX_OUTPUT_TOKENS = 16000

# USD per million tokens (input, output, cache read). Unknown models fall back to Opus rates.
PRICES: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("0.5")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25"), Decimal("0.5")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10"), Decimal("0.2")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5"), Decimal("0.1")),
}
_MTOK = Decimal(1_000_000)


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int) -> Decimal:
    in_rate, out_rate, cache_rate = PRICES.get(model, PRICES[DEFAULT_MODEL])
    uncached = max(input_tokens - cache_read, 0)
    cost = (
        Decimal(uncached) * in_rate
        + Decimal(cache_read) * cache_rate
        + Decimal(output_tokens) * out_rate
    ) / _MTOK
    return cost.quantize(Decimal("0.000001"))


class AnthropicPlanner:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        effort: Literal["low", "medium", "high", "xhigh", "max"] = "high",
        api_key: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        # A zero-arg client resolves ANTHROPIC_API_KEY / `ant auth login` profiles itself.
        self._client = client or (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )

    def plan(self, request: PlanRequest) -> PlannerResult:
        started = time.perf_counter()
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {"role": "user", "content": cast(list[ContentBlockParam], user_content(request))}
            ],
            output_format=PlannerOutput,
            output_config=OutputConfigParam(effort=self.effort),
        )
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        result_usage = Usage(
            provider=PROVIDER,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cost_usd=estimate_cost(self.model, usage.input_tokens, usage.output_tokens, cache_read),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            explanation = getattr(details, "explanation", None) or "the model declined this request"
            return PlannerResult(
                output=None, raw_text=text, usage=result_usage, refusal=explanation
            )
        return PlannerResult(output=response.parsed_output, raw_text=text, usage=result_usage)
