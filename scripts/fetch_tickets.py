"""CLI: fetch closed Freshdesk tickets and print a summary table.

Usage:
    python scripts/fetch_tickets.py [--limit N]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.freshdesk import FreshdeskAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch closed Freshdesk tickets")
    parser.add_argument("--limit", type=int, default=20, help="Max tickets to fetch (default 20)")
    args = parser.parse_args()

    try:
        adapter = FreshdeskAdapter()
    except EnvironmentError as e:
        print(f"Error: {e}")
        print("Copy .env.example to .env and fill in FRESHDESK_DOMAIN and FRESHDESK_API_KEY.")
        sys.exit(1)

    print(f"Fetching up to {args.limit} closed tickets from Freshdesk...\n")
    tickets = adapter.fetch_closed(limit=args.limit)

    if not tickets:
        print("No closed tickets found.")
        return

    col_id    = max(len(t.id) for t in tickets)
    col_title = min(max(len(t.title) for t in tickets), 60)
    col_res   = 20

    header = f"{'ID':<{col_id}}  {'Title':<{col_title}}  {'Resolution note':<{col_res}}"
    print(header)
    print("-" * len(header))

    for t in tickets:
        title = t.title[:col_title - 1] + "…" if len(t.title) > col_title else t.title
        res = "(none)" if not t.resolution_notes else t.resolution_notes[:col_res - 1] + "…" if len(t.resolution_notes) > col_res else t.resolution_notes
        print(f"{t.id:<{col_id}}  {title:<{col_title}}  {res:<{col_res}}")

    print(f"\nFetched {len(tickets)} ticket(s).")
    missing = sum(1 for t in tickets if not t.resolution_notes)
    if missing:
        print(f"Warning: {missing} ticket(s) have no resolution note. Check FRESHDESK_RESOLUTION_FIELD in .env.")


if __name__ == "__main__":
    main()
