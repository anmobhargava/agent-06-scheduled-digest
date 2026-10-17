"""
One digest run, start to finish. This file is the orchestration; the thinking is in crew.py.

  1. monthly cap   already spent this month's budget? stop before any work
  2. collect       fetch feeds (or load the demo samples). No articles means no model calls at all
  3. crew          researcher -> writer -> reviewer, with the per-run cost cap checked after every step
  4. gate          my code re-checks the draft. A reviewer "approved" does not publish anything by itself
  5. revise once   if it did not pass, the writer fixes the listed issues and the reviewer looks again
  6. write         digests/DATE.md if it passed. Otherwise drafts/DATE.md and the status says needs_review
  7. record        runs/DATE.json: status, cost, tokens, issues, which feeds failed

Statuses: published, needs_review, budget_stopped, skipped_budget, no_articles, error.
Nothing here raises for the scheduler. A scheduled job that crashes silently is worse than one that writes down why it stopped.
"""

import dataclasses
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import sources, verify
from .budget import Budget, monthly_ok, usd
from .crew import DigestCrew
from .llms import ROLE_MODEL, have_key, make_llm

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = {"topic": "marketing analytics and measurement", "audience": "marketing analytics lead", "max_picks": 5, "max_words": 450}


@dataclasses.dataclass
class RunResult:
    status: str
    run_date: str
    mode: str                                    # "live" (Claude) or "offline" (scripted stand-in)
    digest: str = ""                             # the rendered markdown with real links, only when published
    draft: str = ""                              # the writer's text, ids not links
    issues: list = dataclasses.field(default_factory=list)
    picks: list = dataclasses.field(default_factory=list)
    revised: bool = False
    cost_usd: float = 0.0                        # what was actually spent. 0 offline
    estimated_cost_usd: float = 0.0              # what those tokens would cost on the live models
    usage: dict = dataclasses.field(default_factory=dict)
    feeds: dict = dataclasses.field(default_factory=dict)
    events: list = dataclasses.field(default_factory=list)
    seconds: float = 0.0
    note: str = ""

    def record(self) -> dict:
        d = dataclasses.asdict(self)
        for big in ("digest", "draft", "events"):
            d.pop(big)
        d["tool_calls"] = sum(1 for e in self.events if e["kind"] == "tool_call")
        return d


def load_feeds() -> list[dict]:
    return yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())["feeds"]


def clean_draft(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text).strip()
    return re.sub(r"^Final Answer:\s*", "", text).strip()


def notes_text(research) -> str:
    return "\n".join(f"{p.id}: {p.why}" for p in research.picks)


def run_digest(demo: bool = False, offline: bool | None = None, days: int = 7, out_dir: Path | None = None, write: bool = True,
               flaws: list[str] | None = None, max_run_usd: float | None = None, on_step=None, revisions: int = 1,
               today: date | None = None) -> RunResult:
    t0 = time.time()
    offline = (not have_key()) if offline is None else offline
    mode = "offline" if offline else "live"
    out_dir = Path(out_dir or (ROOT / "demo_out" if demo else ROOT))
    today = today or date.today()
    result = RunResult(status="", run_date=today.isoformat(), mode=mode)

    def finish(status: str, note: str = "") -> RunResult:
        result.status, result.note, result.seconds = status, note, round(time.time() - t0, 2)
        if write:
            (out_dir / "runs").mkdir(parents=True, exist_ok=True)
            (out_dir / "runs" / f"{result.run_date}.json").write_text(json.dumps(result.record(), indent=1))
        return result

    # 1. monthly cap (a demo run costs nothing real, so it does not count against it)
    if not demo:
        ok, spent, cap = monthly_ok(out_dir / "runs", today)
        if not ok:
            return finish("skipped_budget", f"This month's runs already cost ${spent:.2f}, at or over the ${cap:.2f} monthly cap.")

    # 2. collect
    if demo:
        items, result.feeds, as_of = sources.load_samples(days=days)
        result.run_date = as_of.date().isoformat()
    else:
        as_of = datetime.now(timezone.utc)
        items, result.feeds = sources.collect(load_feeds(), days=days, as_of=as_of)
    if not items:
        return finish("no_articles", "No articles were collected, so no model was called.")
    by_id = {i.id: i for i in items}

    # 3. crew
    llms = {r: make_llm(r, offline=offline, flaws=flaws or []) if offline else make_llm(r, offline=False) for r in ROLE_MODEL}
    budget = Budget(max_run_usd)
    for role, llm in llms.items():
        budget.watch(ROLE_MODEL[role], llm)
    crews: list = []                                                         # holds the crew once it is built, so settle() can read its events
    inputs = {**SETTINGS, "week_of": result.run_date}

    def settle() -> None:
        result.usage, result.events = budget.usage(), (crews[0].events if crews else [])
        result.estimated_cost_usd = usd(result.usage)
        result.cost_usd = 0.0 if offline else result.estimated_cost_usd

    def gate(text: str, said_ok: bool, said: list, picked: set) -> tuple[bool, list]:
        """My code re-checks the draft. The reviewer's 'approved' does not publish anything by itself."""
        problems = verify.check_draft(text, set(by_id), picked, SETTINGS["max_words"], max_bullets=SETTINGS["max_picks"])
        return (said_ok and not problems), list(dict.fromkeys(said + problems))

    def work():
        crew = DigestCrew(items, llms, budget, on_step=on_step)             # built inside the guarded block: a crash here is recorded too
        crews.append(crew)
        outputs = crew.crew().kickoff(inputs=inputs).tasks_output
        if budget.tripped:
            return None
        research, draft, verdict = outputs[0].pydantic, clean_draft(outputs[1].raw), outputs[2].pydantic
        picked = {p.id for p in research.picks}
        approved, issues = gate(draft, bool(verdict and verdict.approved), list(verdict.issues) if verdict else ["The reviewer returned no verdict."], picked)
        if not approved and revisions > 0:                                   # 5. one revision, then stop
            result.revised = True
            rev = crew.revision_crew(notes_text(research)).kickoff(
                inputs={**inputs, "draft": draft, "issues": "\n".join(f"- {x}" for x in issues)})
            if budget.tripped:
                return None
            draft = clean_draft(rev.tasks_output[0].raw)
            v2 = rev.tasks_output[1].pydantic
            approved, issues = gate(draft, bool(v2 and v2.approved), list(v2.issues) if v2 else ["The reviewer returned no verdict."], picked)
        return research, draft, approved, issues

    try:
        with budget.guard():
            done = work()
    except Exception as e:                                                   # a blocked call can surface as any error
        settle()
        if budget.tripped:
            return finish("budget_stopped", budget.message)
        return finish("error", f"{type(e).__name__}: {str(e)[:300]}")
    settle()
    if done is None:
        return finish("budget_stopped", budget.message)
    research, draft, approved, issues = done

    result.draft, result.issues, result.picks = draft, issues, [p.id for p in research.picks]

    # 6. write
    if approved:
        body = verify.render(draft, by_id)
        footer = f"\n\n---\n*Generated {result.run_date} by a researcher, a writer and a reviewer agent. {'Live run with Claude.' if not offline else 'Offline demo: scripted stand-in model, not Claude.'}*\n"
        result.digest = body + footer
        if write:
            (out_dir / "digests").mkdir(parents=True, exist_ok=True)
            (out_dir / "digests" / f"{result.run_date}.md").write_text(result.digest)
        return finish("published")
    if write:
        (out_dir / "drafts").mkdir(parents=True, exist_ok=True)
        (out_dir / "drafts" / f"{result.run_date}.md").write_text(draft + "\n\n<!-- NOT PUBLISHED. Issues:\n" + "\n".join(issues) + "\n-->\n")
    return finish("needs_review", "The draft did not pass the checks after one revision, so it was not published.")
