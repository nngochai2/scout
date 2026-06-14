from abc import ABC, abstractmethod
from agent.models import Ticket


class TicketSource(ABC):
    @abstractmethod
    def fetch_closed(self, limit: int = 50) -> list[Ticket]:
        """Fetch recently closed tickets from the source system."""
        ...
