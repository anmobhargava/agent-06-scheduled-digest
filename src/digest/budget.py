"""
Cost caps. A scheduled job runs while nobody is watching, so it needs limits that do not depend on anyone noticing.

Four caps, from the outside in:
  monthly   add up the cost of every run recorded this month. If that is already over MONTHLY_CAP_USD, do not start
  per run   once this run has spent MAX_RUN_USD, every further model call is blocked (a before-LLM-call hook, see guard())
  per agent each agent gets max_iter steps, so a loop of tool calls cannot go on forever
  per input at most MAX_ITEMS articles, each trimmed, so the prompt size is bounded before any model sees it

The per-run cap is checked before each model call, so a run can overshoot it by at most the one call that crossed the line.
I first tried raising an error from CrewAI's step callback. Its event bus caught the error and carried on, so the run kept
spending. Blocking the call itself is the version that works.
"""

import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .tracing import _price


def usd(usage_by_model: dict) -> float:
    """usage_by_model: {model_name: {"prompt_tokens": n, "completion_tokens": n}} -> dollars."""
    return round(sum(_price(m, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)) for m, u in usage_by_model.items()), 6)


class Budget:
    def __init__(self, max_run_usd: float | None = None):
        self.max_run_usd = float(os.environ.get("MAX_RUN_USD", max_run_usd if max_run_usd is not None else 0.50))
        self.tripped, self.message = False, ""
        self.llms: list[tuple[str, object]] = []             # (model name, an LLM object that counts its own tokens)

    def watch(self, model: str, llm) -> None:
        self.llms.append((model, llm))

    def usage(self) -> dict:
        """Tokens per model, adding up every agent that uses that model."""
        out: dict = {}
        for model, llm in self.llms:
            s = llm.get_token_usage_summary()
            total = out.setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0})
            total["prompt_tokens"] += s.prompt_tokens
            total["completion_tokens"] += s.completion_tokens
        return out

    def spent(self) -> float:
        return usd(self.usage())

    @contextmanager
    def guard(self):
        """While this is active, any model call made after the cap is crossed is blocked. Check `tripped` afterwards."""
        from crewai.hooks import register_before_llm_call_hook, unregister_before_llm_call_hook

        def block_if_over(context):
            spent = self.spent()
            if spent > self.max_run_usd:
                self.tripped = True
                self.message = f"This run has spent ${spent:.4f}, over the ${self.max_run_usd:.2f} cap. Stopped."
                return False                                  # False blocks the call
            return None

        register_before_llm_call_hook(block_if_over)
        try:
            yield self
        finally:
            unregister_before_llm_call_hook(block_if_over)


def month_total(runs_dir: Path, today: date | None = None) -> float:
    today = today or date.today()
    total = 0.0
    for f in runs_dir.glob(f"{today:%Y-%m}-*.json"):
        try:
            total += float(json.loads(f.read_text()).get("cost_usd", 0))
        except (ValueError, OSError):
            continue
    return round(total, 6)


def monthly_ok(runs_dir: Path, today: date | None = None) -> tuple[bool, float, float]:
    cap = float(os.environ.get("MONTHLY_CAP_USD", 5.0))
    spent = month_total(runs_dir, today)
    return spent < cap, spent, cap
