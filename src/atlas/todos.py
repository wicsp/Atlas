from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field, field_validator

from .config import PROJECT_ROOT

DEFAULT_TODO_STORE_PATH = PROJECT_ROOT / "data" / "todos.json"
MAX_TODOS = 500
_STORE_LOCK = Lock()


class TodoNotFoundError(ValueError):
    pass


class TodoItem(BaseModel):
    id: str
    text: str
    done: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class TodoCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Todo text cannot be empty")
        return normalized


class TodoUpdateRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Todo text cannot be empty")
        return normalized


def list_todos(path: Path = DEFAULT_TODO_STORE_PATH) -> list[TodoItem]:
    with _STORE_LOCK:
        return _read_todos(path)


def create_todo(payload: TodoCreateRequest, path: Path = DEFAULT_TODO_STORE_PATH) -> TodoItem:
    with _STORE_LOCK:
        todos = _read_todos(path)
        now = datetime.now(UTC)
        todo = TodoItem(
            id=uuid.uuid4().hex,
            text=payload.text,
            done=False,
            created_at=now,
            updated_at=now,
        )
        todos.insert(0, todo)
        _write_todos(path, todos[:MAX_TODOS])
        return todo


def update_todo(
    todo_id: str,
    payload: TodoUpdateRequest,
    path: Path = DEFAULT_TODO_STORE_PATH,
) -> TodoItem:
    with _STORE_LOCK:
        todos = _read_todos(path)
        for index, todo in enumerate(todos):
            if todo.id != todo_id:
                continue
            updated = todo.model_copy(
                update={
                    "text": payload.text if payload.text is not None else todo.text,
                    "done": payload.done if payload.done is not None else todo.done,
                    "updated_at": datetime.now(UTC),
                }
            )
            todos[index] = updated
            _write_todos(path, todos)
            return updated
    raise TodoNotFoundError(todo_id)


def delete_todo(todo_id: str, path: Path = DEFAULT_TODO_STORE_PATH) -> None:
    with _STORE_LOCK:
        todos = _read_todos(path)
        remaining = [todo for todo in todos if todo.id != todo_id]
        if len(remaining) == len(todos):
            raise TodoNotFoundError(todo_id)
        _write_todos(path, remaining)


def _read_todos(path: Path) -> list[TodoItem]:
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(raw, dict):
        raw_items = raw.get("todos", [])
    else:
        raw_items = raw
    if not isinstance(raw_items, list):
        return []

    todos: list[TodoItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "createdAt" in normalized and "created_at" not in normalized:
            normalized["created_at"] = normalized.pop("createdAt")
        if "updatedAt" in normalized and "updated_at" not in normalized:
            normalized["updated_at"] = normalized.pop("updatedAt")
        try:
            todos.append(TodoItem.model_validate(normalized))
        except ValueError:
            continue
    return todos[:MAX_TODOS]


def _write_todos(path: Path, todos: list[TodoItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [todo.model_dump(mode="json") for todo in todos[:MAX_TODOS]]
    temporary_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
