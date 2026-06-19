import json
from agent.models import Ticket
from ingestion.base import TicketSource

DEFAULT_FIXTURE_PATH = "data/mock_tickets.json"


class MockAdapter(TicketSource):
    def __init__(self, fixture_path: str = DEFAULT_FIXTURE_PATH):
        self._path = fixture_path

    def fetch_closed(self, limit: int = 50) -> list[Ticket]:
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Mock fixture not found: {self._path}")
        return [Ticket(**item) for item in raw[:limit]]
