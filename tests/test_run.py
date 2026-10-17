"""Whole runs through the real CrewAI crew, with the scripted model standing in for Claude."""
import json

from digest import run as runmod
from digest.run import run_digest


def read_record(out, day="2026-10-12"):
    return json.loads((out / "runs" / f"{day}.json").read_text())


def test_a_clean_run_publishes_with_real_links_and_a_record(out):
    r = run_digest(demo=True, offline=True, out_dir=out)
    assert r.status == "published" and not r.revised and r.issues == []
    text = (out / "digests" / "2026-10-12.md").read_text()
    assert "](https://" in text and "[i" not in text and "Offline demo" in text
    rec = read_record(out)
    assert rec["status"] == "published" and rec["mode"] == "offline" and rec["tool_calls"] >= 5
    assert rec["cost_usd"] == 0.0 and rec["estimated_cost_usd"] > 0                  # offline spends nothing, but the estimate is shown
    assert "digest" not in rec and "draft" not in rec


def test_every_agent_actually_used_its_tools(out):
    r = run_digest(demo=True, offline=True, out_dir=out)
    tools = [e["tool"] for e in r.events if e["kind"] == "tool_call"]
    assert tools[0] == "list_items" and "read_item" in tools and tools[-1] == "check_draft"


def test_the_prompt_injection_article_never_reaches_the_digest(out):
    r = run_digest(demo=True, offline=True, out_dir=out)
    assert "evil.example.net" not in r.digest and "Sponsored" not in r.digest


def test_a_missing_citation_is_caught_and_fixed_by_the_one_revision(out):
    r = run_digest(demo=True, offline=True, out_dir=out, flaws=["drop_citation"])
    assert r.status == "published" and r.revised
    assert read_record(out)["revised"] is True


def test_an_injected_link_is_caught_and_never_published(out):
    r = run_digest(demo=True, offline=True, out_dir=out, flaws=["inject_link"])
    assert r.revised and "evil.example.net" not in (out / "digests" / "2026-10-12.md").read_text()


def test_a_rubber_stamping_reviewer_does_not_get_a_bad_draft_published(out):
    """The gate is code. Even with a reviewer that approves everything and a writer that never fixes it, nothing goes out."""
    r = run_digest(demo=True, offline=True, out_dir=out, flaws=["inject_link", "rubber_stamp", "never_fix"])
    assert r.status == "needs_review" and r.revised and any("raw links" in x for x in r.issues)
    assert not (out / "digests").exists() and (out / "drafts" / "2026-10-12.md").exists()
    assert "NOT PUBLISHED" in (out / "drafts" / "2026-10-12.md").read_text()


def test_delegation_the_writer_asks_the_researcher_and_uses_the_answer(out):
    r = run_digest(demo=True, offline=True, out_dir=out, flaws=["delegate"])
    tools = [e["tool"] for e in r.events if e["kind"] == "tool_call"]
    assert "Ask question to coworker" in tools and r.status == "published"
    assert "Measurement teams have asked for this" in r.digest                     # the researcher's answer ended up in the digest


def test_the_per_run_cost_cap_stops_the_run_and_says_so(out):
    r = run_digest(demo=True, offline=True, out_dir=out, max_run_usd=0.005)
    assert r.status == "budget_stopped" and "cap" in r.note
    assert not (out / "digests").exists() and read_record(out)["status"] == "budget_stopped"
    assert r.estimated_cost_usd < 0.03                                              # it stopped early; it did not run the whole crew


def test_the_monthly_cap_skips_the_run_before_any_work(out, monkeypatch):
    (out / "runs").mkdir(parents=True)
    (out / "runs" / "2026-10-01.json").write_text(json.dumps({"cost_usd": 9.0}))
    monkeypatch.setenv("MONTHLY_CAP_USD", "5")
    from datetime import date
    r = run_digest(demo=False, offline=True, out_dir=out, today=date(2026, 10, 14))
    assert r.status == "skipped_budget" and r.usage == {}                           # no crew was built, no model touched


def test_no_articles_means_no_model_call(out, monkeypatch):
    monkeypatch.setattr(runmod.sources, "collect", lambda *a, **k: ([], {"feeds_ok": 0, "feeds_failed": [{"feed": "X", "error": "down"}]}))
    monkeypatch.setattr(runmod, "load_feeds", lambda: [])
    r = run_digest(demo=False, offline=True, out_dir=out)
    assert r.status == "no_articles" and r.usage == {} and r.feeds["feeds_failed"][0]["feed"] == "X"


def test_a_crash_while_building_the_crew_is_recorded_not_raised(out, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("kaboom")
    monkeypatch.setattr(runmod, "DigestCrew", Boom)
    r = run_digest(demo=True, offline=True, out_dir=out)
    assert r.status == "error" and "RuntimeError: kaboom" in r.note and read_record(out)["status"] == "error"


def test_a_failure_inside_the_crew_becomes_an_error_status(out, monkeypatch):
    real = runmod.DigestCrew

    class Fails(real):
        def crew(self):
            raise ValueError("model unavailable")
    monkeypatch.setattr(runmod, "DigestCrew", Fails)
    r = run_digest(demo=True, offline=True, out_dir=out)
    assert r.status == "error" and "ValueError: model unavailable" in r.note
    assert read_record(out)["status"] == "error"


def test_the_demo_writes_to_demo_out_by_default_and_not_the_real_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(runmod, "ROOT", tmp_path)
    run_digest(demo=True, offline=True)
    assert (tmp_path / "demo_out" / "digests").exists() and not (tmp_path / "digests").exists()


def test_clean_draft_removes_code_fences_and_final_answer_prefix():
    assert runmod.clean_draft("```markdown\n# T\n- a [i1]\n```") == "# T\n- a [i1]"
    assert runmod.clean_draft("Final Answer: # T") == "# T"
