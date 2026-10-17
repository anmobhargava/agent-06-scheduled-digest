"""
The checks I do NOT leave to a model.

A reviewer agent is good at "does this overclaim?" and bad at "is every link real?". The second one has a right answer,
so it is code. The writer cites articles by id ([i3]), never by URL. That means a model cannot slip in a link it made up
or one that came from inside an article, because the only way a link reaches the page is through render() below, which
looks the id up in the list of articles that were actually collected.

check_draft() is used twice: as a tool the reviewer can call, and as a final gate after the crew finishes. The gate
matters more. Even if the reviewer approves, nothing is published unless these checks pass.
"""

import re

CITE = re.compile(r"\[(i\d+)\]")
URL = re.compile(r"https?://[^\s)\]>]+")
BULLET = re.compile(r"^\s*[-*]\s+")


def check_draft(draft: str, valid_ids: set[str], picked_ids: set[str] | None = None, max_words: int = 450,
                min_bullets: int = 3, max_bullets: int = 7) -> list[str]:
    """Return a list of problems. An empty list means the draft passed."""
    issues = []
    lines = [ln for ln in draft.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("# "):
        issues.append("The first line must be a title that starts with '# '.")
    bullets = [ln for ln in lines if BULLET.match(ln)]
    if not min_bullets <= len(bullets) <= max_bullets:
        issues.append(f"Use between {min_bullets} and {max_bullets} bullets (found {len(bullets)}).")
    for b in bullets:
        if not CITE.search(b):
            issues.append(f"This bullet has no [id] citation: {b.strip()[:70]}")
    cited = set(CITE.findall(draft))
    for c in sorted(cited - valid_ids):
        issues.append(f"Citation [{c}] is not an article that was collected.")
    if picked_ids is not None:
        for c in sorted((cited & valid_ids) - picked_ids):
            issues.append(f"Citation [{c}] was not one of the researcher's picks.")
    if URL.search(draft):
        issues.append("Remove raw links. Cite by [id] only; links are added automatically.")
    if len(re.findall(r"\w+", draft)) > max_words:
        issues.append(f"Too long: keep it under {max_words} words.")
    return issues


def render(draft: str, items: dict) -> str:
    """Turn [i3] into a real link, using only the collected articles. The one place a URL can enter the digest."""
    def link(m):
        item = items.get(m.group(1))
        return f"[{item.source}]({item.url})" if item else m.group(0)
    return CITE.sub(link, draft)
