from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import MessageCreate, MessageRecord
from .repository import MessageRepository


class MessageStateError(ValueError):
    pass


class MessageService:
    def __init__(self, repository: MessageRepository) -> None:
        self._repository = repository

    def send_message(
        self,
        payload: MessageCreate,
        now: datetime | None = None,
    ) -> MessageRecord:
        return self._repository.create(payload, now or datetime.now(UTC))

    def get_message(self, message_id: str) -> MessageRecord:
        return self._repository.get(message_id)

    def list_inbox(self, agent_id: str, limit: int = 50) -> list[MessageRecord]:
        return self._repository.list_pending_for_agent(agent_id, limit=limit)

    def claim_message(
        self,
        message_id: str,
        agent_id: str,
        now: datetime | None = None,
    ) -> MessageRecord:
        message = self._repository.get(message_id)
        if message.to_agent_id != agent_id:
            raise PermissionError(message_id)
        if message.status != "pending":
            raise MessageStateError(f"Message {message_id} is not pending")
        return self._repository.claim(message_id, agent_id, now or datetime.now(UTC))

    def acknowledge_message(
        self,
        message_id: str,
        agent_id: str,
        result: str | None = None,
        now: datetime | None = None,
    ) -> MessageRecord:
        message = self._repository.get(message_id)
        if message.to_agent_id != agent_id:
            raise PermissionError(message_id)
        if message.status != "claimed":
            raise MessageStateError(f"Message {message_id} is not claimed")
        if message.claimed_by != agent_id:
            raise PermissionError(message_id)
        return self._repository.acknowledge(message_id, result, now or datetime.now(UTC))


def create_message_service(database_path: Path) -> MessageService:
    return MessageService(MessageRepository(create_sqlite_session_factory(database_path)))
