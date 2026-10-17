"""The command line and the Gradio page."""
import pytest

from digest import app, main
from digest.llms import ROLE_MODEL, make_llm


def test_cli_demo_runs_and_exits_zero(capsys, tmp_path, monkeypatch):
    from digest import run as runmod
    monkeypatch.setattr(runmod, "ROOT", tmp_path)
    assert main.main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "status: published" in out and "mode: offline" in out


def test_cli_refuses_a_real_run_without_a_key_unless_told_otherwise(capsys):
    assert main.main([]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_models_are_routed_small_for_reading_and_large_for_writing():
    assert ROLE_MODEL["writer"] != ROLE_MODEL["researcher"] and ROLE_MODEL["researcher"] == ROLE_MODEL["reviewer"]
    assert "haiku" in ROLE_MODEL["researcher"] and "sonnet" in ROLE_MODEL["writer"]


def test_without_a_key_make_llm_gives_the_scripted_stand_in():
    assert make_llm("writer").llm_type == "scripted"


def final(gen):
    out = None
    for out in gen:
        pass
    return out


def test_the_page_runs_the_demo_and_shows_digest_steps_and_checks():
    status, digest, steps, checks, runs = final(app.go(app.DEMO, "Nothing, run it normally", 0))
    assert "Published" in status and digest.startswith("# Marketing measurement digest")
    assert "list_items" in steps and "check_draft" in steps and "Cost:" in checks and runs == 0     # demo runs are not counted


def test_the_page_shows_why_a_bad_draft_was_not_published():
    status, digest, steps, checks, _ = final(app.go(app.DEMO, "Reviewer rubber-stamps and writer never fixes it", 0))
    assert "Not published" in status and digest.startswith("**Draft (not published)") and "raw links" in checks


def test_live_mode_without_a_key_explains_itself_and_counts_nothing():
    status, _, _, _, runs = final(app.go(app.LIVE, "Nothing, run it normally", 0))
    assert "ANTHROPIC_API_KEY" in status and runs == 0


def test_live_runs_are_capped_per_visit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    status, *_ = final(app.go(app.LIVE, "Nothing, run it normally", app.MAX_LIVE_RUNS))
    assert "used your" in status


def test_every_variation_in_the_dropdown_is_a_known_scripted_flaw():
    known = {"drop_citation", "inject_link", "rubber_stamp", "never_fix", "delegate"}
    assert all(set(v) <= known for v in app.BREAK.values())
