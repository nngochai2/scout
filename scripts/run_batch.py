"""CLI: run the Scout daily batch — fetch → triage → investigate → persist.

Usage:
    python scripts/run_batch.py [--limit N] [--triage-only]
"""
import argparse
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from agent.database import init_db
from agent.triage import triage_batch
from agent.investigate import investigate
from agent.models import TriageVerdict
from ingestion.freshdesk import FreshdeskAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="Scout daily triage batch")
    parser.add_argument("--limit", type=int, default=20, help="Max tickets to fetch (default 20)")
    parser.add_argument(
        "--triage-only",
        action="store_true",
        help="Run triage only; skip investigation",
    )
    args = parser.parse_args()

    init_db()

    try:
        adapter = FreshdeskAdapter()
    except EnvironmentError as e:
        print(f"Error: {e}")
        print("Copy .env.example to .env and fill in FRESHDESK_DOMAIN and FRESHDESK_API_KEY.")
        sys.exit(1)

    print(f"Fetching up to {args.limit} closed tickets from Freshdesk...")
    tickets = adapter.fetch_closed(limit=args.limit)
    if not tickets:
        print("No tickets found.")
        return
    print(f"Fetched {len(tickets)} ticket(s).\n")

    print("--- Triage gate ---")
    triage_results = triage_batch(tickets)

    counts = Counter(r.verdict.value for r in triage_results)
    print(f"\nTriage complete ({len(triage_results)} results):")
    for verdict, n in sorted(counts.items()):
        print(f"  {verdict}: {n}")

    if args.triage_only:
        print("\n--triage-only: skipping investigation.")
        return

    to_investigate = [r for r in triage_results if r.verdict == TriageVerdict.INVESTIGATE]
    if not to_investigate:
        print("\nNo tickets escalated to investigation.")
        return

    ticket_map = {t.id: t for t in tickets}
    print(f"\n--- Investigation ({len(to_investigate)} ticket(s)) ---")

    for triage in to_investigate:
        ticket = ticket_map.get(triage.ticket_id)
        if ticket is None:
            print(f"  [{triage.ticket_id}] ticket not found in fetch result — skipping")
            continue

        print(f"  [{ticket.id}] {ticket.title[:70]}")
        try:
            diagnosis = investigate(ticket, triage)
            cause = diagnosis.root_cause or "(insufficient evidence)"
            print(f"    confidence={diagnosis.confidence.value}  cause={cause[:100]}")
        except Exception as exc:
            print(f"    ERROR: {exc!r}")

    print("\nBatch complete.")


if __name__ == "__main__":
    main()
