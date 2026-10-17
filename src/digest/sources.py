"""
Step one of every run: collect the articles. No agents here, on purpose.

Fetching feeds is plain work with a right answer, so it is plain Python. The crew only gets involved once there is a pile of
articles to choose from. That keeps the model's budget for the parts that need judgement (what matters, how to say it).

What this does:
  1. read the feed list from config/sources.yaml
  2. fetch each feed on its own thread, with a timeout. One dead feed is noted and skipped, it never stops the run
  3. parse RSS or Atom with the standard library (no feed parser dependency)
  4. drop duplicates (same link, or almost the same headline from two outlets)
  5. keep only recent items, newest first, capped, so the crew cannot be handed 400 articles

Everything that comes out of a feed is UNTRUSTED text. Somebody can write "ignore your instructions" inside an article.
Nothing in this file interprets that text. tools.py wraps it as data before an agent sees it, and verify.py checks the
finished digest against the list of articles that were really collected.
"""

import dataclasses
import difflib
import hashlib
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "scheduled-digest-agent/0.1 (portfolio project)"
TAG = re.compile(r"<[^>]+>")


@dataclasses.dataclass
class Item:
    id: str                    # i1, i2, ... the only way the crew refers to an article
    title: str
    url: str
    source: str
    published: str             # ISO date, "" if the feed gave none
    summary: str               # plain text, trimmed
    body: str = ""             # longer text when the demo samples or an article fetch provide it


def clean(text: str, limit: int = 600) -> str:
    """HTML to plain text, collapsed whitespace, trimmed."""
    text = html.unescape(TAG.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)                              # RSS: "Tue, 07 Oct 2026 10:00:00 GMT"
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom: "2026-10-07T10:00:00Z"
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str, source: str) -> list[dict]:
    """RSS 2.0 and Atom. Returns plain dicts; ids are assigned later, after dedupe."""
    root = ET.fromstring(xml_text)
    out = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        fields = {c.tag.split("}")[-1]: c for c in node}
        link = ""
        if "link" in fields:
            link = fields["link"].get("href") or (fields["link"].text or "")      # Atom keeps it in an attribute
        title = clean(getattr(fields.get("title"), "text", "") or "", 200)
        body = ""
        for k in ("encoded", "content", "description", "summary"):
            if k in fields and (fields[k].text or "").strip():
                body = fields[k].text
                break
        when = ""
        for k in ("pubDate", "published", "updated", "date"):
            if k in fields and fields[k].text:
                d = parse_date(fields[k].text)
                if d:
                    when = d.date().isoformat()
                    break
        if title and link.startswith("http"):
            out.append({"title": title, "url": link.strip(), "source": source, "published": when, "summary": clean(body, 600),
                        "body": clean(body, 2500)})
    return out


def fetch(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:                 # noqa: S310  (feed URLs come from my own config file)
        return r.read().decode("utf-8", errors="replace")


def cached_fetch(url: str, ttl_hours: float, cache_dir: Path) -> str:
    """A feed is not re-downloaded within the TTL. It is polite to the publisher, and re-runs during development are free."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".xml")
    if path.exists() and time.time() - path.stat().st_mtime < ttl_hours * 3600:
        return path.read_text()
    text = fetch(url)
    path.write_text(text)
    return text


def normalise_url(url: str) -> str:
    url = re.sub(r"[?#].*$", "", url.lower())                               # tracking parameters differ, the article does not
    return url.rstrip("/")


def dedupe(rows: list[dict], similar: float = 0.75) -> list[dict]:
    seen_urls, kept = set(), []
    for r in rows:
        key = normalise_url(r["url"])
        if key in seen_urls:
            continue
        if any(difflib.SequenceMatcher(None, r["title"].lower(), k["title"].lower()).ratio() >= similar for k in kept):
            continue                                                         # the same story from a second outlet
        seen_urls.add(key)
        kept.append(r)
    return kept


def collect(feeds: list[dict], days: int = 7, limit: int = 30, as_of: datetime | None = None,
            ttl_hours: float = 3, cache_dir: Path | None = None) -> tuple[list[Item], dict]:
    """Fetch every feed and return (items, report). The report says which feeds failed and why, so a quiet feed is never a mystery."""
    cache_dir = cache_dir or ROOT / "data" / "cache"
    as_of = as_of or datetime.now(timezone.utc)
    report = {"feeds_ok": 0, "feeds_failed": [], "raw_items": 0}

    def one(feed):
        try:
            return feed, parse_feed(cached_fetch(feed["url"], ttl_hours, cache_dir), feed["name"]), None
        except Exception as e:                                               # a dead feed must never stop the run
            return feed, [], f"{type(e).__name__}: {str(e)[:120]}"

    rows = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for feed, got, err in pool.map(one, feeds):
            if err:
                report["feeds_failed"].append({"feed": feed["name"], "error": err})
            else:
                report["feeds_ok"] += 1
                rows += got
    report["raw_items"] = len(rows)
    return finish(rows, days, limit, as_of, report)


def finish(rows: list[dict], days: int, limit: int, as_of: datetime, report: dict) -> tuple[list[Item], dict]:
    """Shared by live feeds and the demo samples: filter by age, dedupe, sort newest first, cap, assign ids."""
    cutoff = (as_of - timedelta(days=days)).date().isoformat()
    recent = [r for r in rows if r["published"] and r["published"] >= cutoff]
    recent.sort(key=lambda r: r["published"], reverse=True)
    kept = dedupe(recent)[:limit]
    items = [Item(id=f"i{n}", **r) for n, r in enumerate(kept, 1)]
    report.update({"kept": len(items), "dropped_old_or_undated": len(rows) - len(recent), "dropped_duplicates": len(recent) - len(dedupe(recent))})
    return items, report


def load_samples(path: Path | None = None, days: int = 7, limit: int = 30) -> tuple[list[Item], dict, datetime]:
    """The demo: invented articles from samples/articles.json. 'Today' is the newest sample date, so the demo never goes stale."""
    rows = json.loads((path or ROOT / "samples" / "articles.json").read_text())
    newest = max(r["published"] for r in rows)
    as_of = datetime.fromisoformat(newest).replace(tzinfo=timezone.utc)
    items, report = finish(rows, days, limit, as_of, {"feeds_ok": 0, "feeds_failed": [], "raw_items": len(rows), "demo": True})
    return items, report, as_of
