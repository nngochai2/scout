import os
from datetime import datetime
from html.parser import HTMLParser

import httpx
from dotenv import load_dotenv

from agent.models import Ticket
from ingestion.base import TicketSource

load_dotenv()

# Freshdesk status codes
_STATUS_RESOLVED = 4
_STATUS_CLOSED = 5


class _StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def result(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(raw: str) -> str:
    parser = _StripHTML()
    parser.feed(raw or "")
    return parser.result()


class FreshdeskAdapter(TicketSource):
    """Fetches closed Freshdesk tickets and maps them to the canonical Ticket model.

    Expects these env vars:
      FRESHDESK_DOMAIN          e.g. yourcompany.freshdesk.com
      FRESHDESK_API_KEY         Freshdesk API key
      FRESHDESK_RESOLUTION_FIELD  custom field name holding the resolution note
                                  (default: cf_resolution — confirm with team)
    """

    def __init__(self) -> None:
        domain = os.getenv("FRESHDESK_DOMAIN")
        api_key = os.getenv("FRESHDESK_API_KEY")
        if not domain or not api_key:
            raise EnvironmentError(
                "FRESHDESK_DOMAIN and FRESHDESK_API_KEY must be set in .env"
            )
        self._base_url = f"https://{domain}/api/v2"
        self._auth = (api_key, "X")  # Freshdesk uses api_key:X basic auth
        self._resolution_field = os.getenv("FRESHDESK_RESOLUTION_FIELD", "cf_resolution")

    def fetch_closed(self, limit: int = 50) -> list[Ticket]:
        """Fetch recently resolved or closed tickets, newest first."""
        tickets: list[Ticket] = []
        page = 1

        while len(tickets) < limit:
            batch = self._fetch_page(page)
            if not batch:
                break
            tickets.extend(batch)
            if len(batch) < 30:  # Freshdesk default page size is 30
                break
            page += 1

        return tickets[:limit]

    def _fetch_page(self, page: int) -> list[Ticket]:
        response = httpx.get(
            f"{self._base_url}/tickets",
            auth=self._auth,
            params={
                "status": _STATUS_CLOSED,
                "order_by": "updated_at",
                "order_type": "desc",
                "per_page": 30,
                "page": page,
                "include": "description",
            },
            timeout=30,
        )
        response.raise_for_status()
        return [self._map(raw) for raw in response.json()]

    def _map(self, raw: dict) -> Ticket:
        custom = raw.get("custom_fields") or {}
        resolution = custom.get(self._resolution_field)

        created_raw = raw.get("created_at")
        created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00")) if created_raw else None

        return Ticket(
            id=str(raw["id"]),
            title=raw.get("subject", ""),
            description=_strip_html(raw.get("description", "")),
            status=str(raw.get("status", "")),
            created_at=created_at,
            resolution_notes=resolution,
            source_system="freshdesk",
        )
