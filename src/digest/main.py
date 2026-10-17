"""
Command line entry point. This is what the scheduler runs.

  python -m digest.main --demo        offline demo on the invented sample articles. Needs nothing. Writes to demo_out/
  python -m digest.main               the real thing: live feeds, Claude, writes digests/ and runs/

The real run needs ANTHROPIC_API_KEY. Without a key I refuse instead of publishing a digest written by the scripted stand-in,
because a scheduled job that quietly publishes junk is worse than one that stops. Add --allow-offline to override that.

Exit code 0 means a digest was published (or there was nothing to do). Anything else means a person should look,
and the run record in runs/ says why.
"""

import argparse
import os
import sys

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")      # no usage reporting from the crew library
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from .llms import have_key                                     # noqa: E402
from .run import run_digest                                    # noqa: E402

OK = {"published", "no_articles", "skipped_budget"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the weekly digest crew once.")
    ap.add_argument("--demo", action="store_true", help="use the invented sample articles and the scripted stand-in model")
    ap.add_argument("--days", type=int, default=7, help="how many days back to read")
    ap.add_argument("--max-run-usd", type=float, default=None, help="stop this run once it has spent this much (default 0.50)")
    ap.add_argument("--allow-offline", action="store_true", help="let a non-demo run use the scripted stand-in when there is no key")
    ap.add_argument("--no-write", action="store_true", help="print the digest and write no files")
    args = ap.parse_args(argv)

    if not args.demo and not have_key() and not args.allow_offline:
        print("No ANTHROPIC_API_KEY, so I will not run a real digest. Use --demo to see it work offline.", file=sys.stderr)
        return 2
    r = run_digest(demo=args.demo, days=args.days, max_run_usd=args.max_run_usd, write=not args.no_write,
                   offline=True if args.demo else None)
    print(r.digest or r.draft or "(no digest)")
    print(f"\nstatus: {r.status} | mode: {r.mode} | picks: {len(r.picks)} | revised: {r.revised} | "
          f"cost: ${r.cost_usd:.4f} (estimate if live: ${r.estimated_cost_usd:.4f}) | {r.seconds}s")
    if r.note:
        print("note:", r.note)
    if r.issues:
        print("issues:", *[f"- {x}" for x in r.issues], sep="\n")
    if r.feeds.get("feeds_failed"):
        print("feeds that failed:", *[f"- {f['feed']}: {f['error']}" for f in r.feeds["feeds_failed"]], sep="\n")
    return 0 if r.status in OK else 1


if __name__ == "__main__":
    sys.exit(main())
