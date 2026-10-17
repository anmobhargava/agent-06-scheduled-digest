"""Collecting articles: parsing, dropping duplicates and old items, and surviving a dead feed."""
import json
from datetime import datetime, timezone
from pathlib import Path

from digest import sources
from digest.sources import clean, dedupe, finish, load_samples, parse_date, parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Brands test &amp; learn</title><link>https://a.example.com/x?utm=1</link><pubDate>Tue, 07 Oct 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Spend rose &lt;b&gt;12%&lt;/b&gt;.&lt;/p&gt;</description></item>
<item><title>No link here</title><pubDate>Tue, 07 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom story</title>
<link href="https://b.example.com/atom"/><updated>2026-10-08T09:00:00Z</updated><summary>Short summary.</summary></entry></feed>"""


def test_rss_is_parsed_html_is_stripped_and_items_without_links_are_dropped():
    rows = parse_feed(RSS, "A")
    assert len(rows) == 1 and rows[0]["title"] == "Brands test & learn"
    assert rows[0]["published"] == "2026-10-07" and rows[0]["summary"] == "Spend rose 12% ." or "12%" in rows[0]["summary"]
    assert "<" not in rows[0]["body"]


def test_atom_keeps_its_link_in_the_href_attribute():
    rows = parse_feed(ATOM, "B")
    assert rows[0]["url"] == "https://b.example.com/atom" and rows[0]["published"] == "2026-10-08"


def test_dates_in_both_formats_and_garbage():
    assert parse_date("Tue, 07 Oct 2026 10:00:00 GMT").date().isoformat() == "2026-10-07"
    assert parse_date("2026-10-08T09:00:00Z").date().isoformat() == "2026-10-08"
    assert parse_date("not a date") is None and parse_date("") is None


def test_dedupe_drops_same_link_and_the_same_story_but_keeps_different_ones():
    rows = [{"title": "Retail media networks agree on a common reporting template", "url": "https://x.example.com/a?ref=1"},
            {"title": "Something else entirely about consent", "url": "https://x.example.com/c"},
            {"title": "Retail media networks agree on a common reporting template", "url": "https://x.example.com/a?ref=2"},
            {"title": "Retail media networks publish shared reporting template", "url": "https://y.example.com/b"}]
    kept = dedupe(rows)
    assert [r["url"] for r in kept] == ["https://x.example.com/a?ref=1", "https://x.example.com/c"]


def test_finish_drops_old_and_undated_sorts_newest_first_caps_and_numbers_the_ids():
    as_of = datetime(2026, 10, 12, tzinfo=timezone.utc)
    rows = [{"title": f"t{i}", "url": f"https://e.example.com/{i}", "source": "S", "published": d, "summary": "", "body": ""}
            for i, d in enumerate(["2026-10-05", "2026-10-11", "", "2026-09-01", "2026-10-09"])]
    items, rep = finish(rows, days=7, limit=2, as_of=as_of, report={})
    assert [i.id for i in items] == ["i1", "i2"] and [i.published for i in items] == ["2026-10-11", "2026-10-09"]
    assert rep["dropped_old_or_undated"] == 2


def test_a_dead_feed_is_reported_and_does_not_stop_the_others(monkeypatch, tmp_path):
    def fake(url, ttl, cache):
        if "bad" in url:
            raise OSError("connection refused")
        return ATOM
    monkeypatch.setattr(sources, "cached_fetch", fake)
    feeds = [{"name": "Good", "url": "https://good.example.com/f"}, {"name": "Bad", "url": "https://bad.example.com/f"}]
    items, rep = sources.collect(feeds, days=7, as_of=datetime(2026, 10, 10, tzinfo=timezone.utc), cache_dir=tmp_path)
    assert len(items) == 1 and rep["feeds_ok"] == 1 and rep["feeds_failed"][0]["feed"] == "Bad" and "OSError" in rep["feeds_failed"][0]["error"]


def test_feed_cache_is_used_inside_the_ttl(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sources, "fetch", lambda url, timeout=15: calls.append(url) or ATOM)
    sources.cached_fetch("https://c.example.com/f", 3, tmp_path)
    sources.cached_fetch("https://c.example.com/f", 3, tmp_path)
    assert len(calls) == 1


def test_demo_samples_contain_the_traps_on_purpose():
    items, rep, as_of = load_samples()
    assert as_of.date().isoformat() == "2026-10-12"
    assert rep["dropped_duplicates"] == 1 and rep["dropped_old_or_undated"] == 2
    assert any("ignore all previous instructions" in i.body.lower() for i in items)          # an injection attempt is in the pile


def test_clean_text():
    assert clean("<p>a &amp;  b</p>\n<b>c</b>") == "a & b c"
