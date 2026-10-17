"""
A small demo page. Press a button, watch the three agents work, read the digest.

  python -m digest.app        then open http://localhost:7860

Demo mode runs on the invented sample articles with the scripted stand-in model, so it needs no key and costs nothing.
The variation box changes what the stand-in does, so you can watch delegation, or the checks catching a mistake:
  ask the researcher     the writer asks the researcher a question (CrewAI delegation) and uses the answer
  drop a citation        the writer forgets one [id]. The reviewer's tool flags it and the writer fixes it
  obey an injected link  the writer pastes a link that an article told it to. The link check flags it
  rubber-stamp + stuck   the reviewer approves anything and the writer never fixes it. My gate still refuses to publish

Live mode needs ANTHROPIC_API_KEY, reads the real feeds, and is capped at MAX_LIVE_RUNS runs per page visit.
"""

import os
import queue
import threading

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr                                                    # noqa: E402

from .llms import have_key                                            # noqa: E402
from .run import run_digest                                           # noqa: E402

MAX_LIVE_RUNS = int(os.environ.get("MAX_LIVE_RUNS", "3"))
BREAK = {
    "Nothing, run it normally": [],
    "Writer asks the researcher a question (delegation)": ["delegate"],
    "Writer forgets a citation": ["drop_citation"],
    "Writer obeys an injected link": ["inject_link"],
    "Reviewer rubber-stamps and writer never fixes it": ["inject_link", "rubber_stamp", "never_fix"],
}
LIVE = "Live (real feeds, Claude)"
DEMO = "Demo (invented articles, no key)"
STATUS_TEXT = {
    "published": "Published. The draft passed every check.",
    "needs_review": "Not published. The draft failed the checks after one revision, so it was saved as a draft only.",
    "budget_stopped": "Stopped by the cost cap.",
    "skipped_budget": "Skipped: this month's cost cap was already reached.",
    "no_articles": "Nothing to do: no articles were collected, so no model was called.",
    "error": "The run hit an error. Details below.",
}


def render_steps(events: list[dict]) -> str:
    lines = []
    for e in events:
        if e["kind"] == "tool_call":
            lines.append(f"- tool call: `{e['tool']}` {e['input'][:70]}")
    return "\n".join(lines) or "_Waiting for the first step..._"


def go(mode: str, broken: str, live_runs: int):
    live = mode == LIVE
    if live and not have_key():
        yield "Live mode needs ANTHROPIC_API_KEY on the server. Use the demo.", "", "", "", live_runs
        return
    if live and live_runs >= MAX_LIVE_RUNS:
        yield f"You have used your {MAX_LIVE_RUNS} live runs for this visit.", "", "", "", live_runs
        return
    q: queue.Queue = queue.Queue()
    events: list[dict] = []

    def work():
        try:
            q.put(("done", run_digest(demo=not live, offline=None if live else True, write=False, flaws=[] if live else BREAK[broken],
                                      on_step=lambda e: q.put(("step", e)))))
        except Exception as e:
            q.put(("error", e))

    threading.Thread(target=work, daemon=True).start()
    yield "Running: researcher, then writer, then reviewer...", "", render_steps(events), "", live_runs
    while True:
        kind, payload = q.get()
        if kind == "step":
            events.append(payload)
            yield "Running...", "", render_steps(events), "", live_runs
            continue
        if kind == "error":
            yield f"The run failed: {type(payload).__name__}: {payload}", "", render_steps(events), "", live_runs
            return
        r = payload
        status = f"**{STATUS_TEXT.get(r.status, r.status)}**"
        if r.note and r.status in ("budget_stopped", "skipped_budget", "error"):    # the other statuses already say it
            status += f"\n\n{r.note}"
        checks = ("\n".join(f"- {x}" for x in r.issues) or "_No issues. The reviewer approved and the mechanical checks passed._")
        if r.revised:
            checks = "_The first draft failed, so the writer revised it once._\n\n" + checks
        cost = (f"Cost: **${r.cost_usd:.4f}** spent. If this had run on Claude it would have cost about ${r.estimated_cost_usd:.4f}. "
                f"Mode: {r.mode}. {r.seconds}s.")
        yield status, r.digest or (f"**Draft (not published):**\n\n```markdown\n{r.draft}\n```" if r.draft else ""), render_steps(r.events), checks + "\n\n" + cost, live_runs + (1 if live else 0)
        return


def build() -> gr.Blocks:
    with gr.Blocks(title="Scheduled digest agent") as demo:
        gr.Markdown("# Scheduled digest agent\nA researcher, a writer and a reviewer agent make a weekly marketing measurement digest. "
                    "On a schedule it runs by itself, with a cost cap and a final check before anything is published.")
        gr.Markdown("**Demo mode:** invented articles and a scripted stand-in for Claude. It shows the teamwork and the guards, not the writing quality."
                    if not have_key() else "**A Claude key is set**, so live mode is available.")
        runs = gr.State(0)
        with gr.Row():
            mode = gr.Radio([DEMO, LIVE], value=DEMO, label="Mode")
            broken = gr.Dropdown(list(BREAK), value=list(BREAK)[0], label="Try a variation (demo only)")
        run = gr.Button("Run the digest", variant="primary")
        status = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### Digest")
                digest = gr.Markdown()
            with gr.Column(scale=2):
                gr.Markdown("### What the agents did")
                steps = gr.Markdown()
                gr.Markdown("### Checks")
                checks = gr.Markdown()
        run.click(go, [mode, broken, runs], [status, digest, steps, checks, runs])
    return demo


if __name__ == "__main__":
    build().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")), theme=gr.themes.Soft())
