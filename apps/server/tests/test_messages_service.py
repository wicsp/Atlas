from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atlas.messages.models import MessageCreate
from atlas.messages.service import MessageStateError, create_message_service


def make_service(tmp_path: Path):
    return create_message_service(tmp_path / "atlas.sqlite3")


def message_payload() -> MessageCreate:
    return MessageCreate(
        from_agent_id="mac-dev",
        to_agent_id="amax-prod",
        kind="prompt",
        body="please inspect the failing job",
        metadata={"priority": "normal"},
    )


def test_send_message_persists_pending_message(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    now = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)

    message = service.send_message(message_payload(), now=now)
    fetched = service.get_message(message.message_id)

    assert message.message_id.startswith("msg_")
    assert fetched == message
    assert message.from_agent_id == "mac-dev"
    assert message.to_agent_id == "amax-prod"
    assert message.kind == "prompt"
    assert message.body == "please inspect the failing job"
    assert message.metadata == {"priority": "normal"}
    assert message.status == "pending"
    assert message.created_at == now
    assert message.claimed_at is None
    assert message.acknowledged_at is None
    assert message.result is None


def test_inbox_lists_only_pending_messages_for_target_agent(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    now = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    target_message = service.send_message(message_payload(), now=now)
    service.send_message(
        MessageCreate(from_agent_id="mac-dev", to_agent_id="other-agent", body="wrong inbox"),
        now=now + timedelta(seconds=1),
    )
    claimed_message = service.send_message(
        MessageCreate(from_agent_id="mac-dev", to_agent_id="amax-prod", body="claimed"),
        now=now + timedelta(seconds=2),
    )
    service.claim_message(claimed_message.message_id, agent_id="amax-prod", now=now)

    inbox = service.list_inbox("amax-prod")

    assert [message.message_id for message in inbox] == [target_message.message_id]


def test_target_agent_can_claim_pending_message(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created_at = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    claimed_at = created_at + timedelta(seconds=10)
    message = service.send_message(message_payload(), now=created_at)

    claimed = service.claim_message(message.message_id, agent_id="amax-prod", now=claimed_at)

    assert claimed.status == "claimed"
    assert claimed.claimed_by == "amax-prod"
    assert claimed.claimed_at == claimed_at


def test_non_target_agent_cannot_claim_message(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    message = service.send_message(message_payload())

    with pytest.raises(PermissionError):
        service.claim_message(message.message_id, agent_id="mac-dev")


def test_acknowledgement_requires_claimed_message(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    message = service.send_message(message_payload())

    with pytest.raises(MessageStateError):
        service.acknowledge_message(
            message.message_id,
            agent_id="amax-prod",
            result="queued",
        )


def test_target_agent_can_acknowledge_claimed_message(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created_at = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    acknowledged_at = created_at + timedelta(seconds=20)
    message = service.send_message(message_payload(), now=created_at)
    service.claim_message(message.message_id, agent_id="amax-prod", now=created_at)

    acknowledged = service.acknowledge_message(
        message.message_id,
        agent_id="amax-prod",
        result="investigation queued",
        now=acknowledged_at,
    )

    assert acknowledged.status == "acknowledged"
    assert acknowledged.result == "investigation queued"
    assert acknowledged.acknowledged_at == acknowledged_at
