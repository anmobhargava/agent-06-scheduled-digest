"""
Which model each role uses, and the offline stand-in.

Model routing is a cost decision. The researcher and the reviewer mostly read and tick things off, so they run on the small
model. Only the writer, whose output people read, runs on the larger one. Override any of them with an environment variable.

No ANTHROPIC_API_KEY means the crew runs on ScriptedLLM (scripted.py): the real CrewAI agents, tasks, tools and handoffs,
with a rule-based model standing in for Claude. The result says which one ran.
"""

import os

SMALL = os.environ.get("SMALL_MODEL", "claude-haiku-4-5-20251001")
LARGE = os.environ.get("LARGE_MODEL", "claude-sonnet-5-5")
ROLE_MODEL = {"researcher": SMALL, "writer": LARGE, "reviewer": SMALL}


def have_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))



