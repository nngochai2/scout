import pytest
from ingestion.mock import MockAdapter


def test_loads_tickets_from_fixture(ticket_fixture):
    adapter = MockAdapter(fixture_path=ticket_fixture)
    tickets = adapter.fetch_closed()
    assert len(tickets) == 3
    assert tickets[0].id == "T001"
    assert tickets[0].title == "Login fails with SSO"
    assert tickets[0].source_system == "mock"


def test_limit_is_respected(ticket_fixture):
    adapter = MockAdapter(fixture_path=ticket_fixture)
    tickets = adapter.fetch_closed(limit=2)
    assert len(tickets) == 2
    assert tickets[0].id == "T001"
    assert tickets[1].id == "T002"


def test_missing_fixture_raises_with_path():
    adapter = MockAdapter(fixture_path="/no/such/file.json")
    with pytest.raises(FileNotFoundError, match="/no/such/file.json"):
        adapter.fetch_closed()
