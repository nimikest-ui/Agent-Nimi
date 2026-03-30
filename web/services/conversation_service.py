"""Conversation management service."""
import json
import datetime
from pathlib import Path
from typing import Optional

CONV_DIR = Path.home() / ".agent-nimi" / "conversations"
ARCHIVE_DIR = Path.home() / ".agent-nimi" / "conversation_archive"
CONV_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _conv_path(conv_id: str) -> Path:
    """Get the file path for a conversation."""
    return CONV_DIR / f"{conv_id}.json"


def _archive_path(conv_id: str) -> Path:
    """Get the archive file path for a conversation."""
    return ARCHIVE_DIR / f"{conv_id}.json"


def _snippet(text: str, limit: int = 220) -> str:
    """Return a compact one-line snippet."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _build_archive_record(conv: dict) -> dict:
    """Create an archived conversation record with lightweight summary fields."""
    messages = conv.get("messages", [])
    user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
    assistant_messages = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
    archived = dict(conv)
    archived["archived_at"] = datetime.datetime.now().isoformat()
    archived["archive_summary"] = {
        "title": conv.get("title", "Untitled"),
        "message_count": len(messages),
        "first_user_message": _snippet(user_messages[0]) if user_messages else "",
        "last_user_message": _snippet(user_messages[-1]) if user_messages else "",
        "last_assistant_message": _snippet(assistant_messages[-1]) if assistant_messages else "",
    }
    return archived


def save_conversation(conv_id: str, data: dict):
    """Save a conversation to disk."""
    data["updated_at"] = datetime.datetime.now().isoformat()
    with open(_conv_path(conv_id), "w") as f:
        json.dump(data, f, indent=2)


def load_conversation(conv_id: str) -> Optional[dict]:
    """Load a conversation from disk."""
    p = _conv_path(conv_id)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def list_conversations() -> list[dict]:
    """List all saved conversations."""
    convs = []
    for p in CONV_DIR.glob("*.json"):
        try:
            with open(p) as f:
                data = json.load(f)
            convs.append({
                "id": data.get("id", p.stem),
                "title": data.get("title", "Untitled"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    convs.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return convs


def generate_title(message: str) -> str:
    """Generate a short title from the first user message."""
    title = message.strip().replace("\n", " ")
    if len(title) > 50:
        title = title[:47] + "..."
    return title


def delete_conversation(conv_id: str) -> bool:
    """Delete a conversation."""
    p = _conv_path(conv_id)
    if p.exists():
        p.unlink()
        return True
    return False


def archive_conversation(conv_id: str) -> bool:
    """Remove a conversation from recents while preserving its contents in the archive."""
    conv = load_conversation(conv_id)
    if not conv:
        return False
    archived = _build_archive_record(conv)
    with open(_archive_path(conv_id), "w") as f:
        json.dump(archived, f, indent=2)
    return delete_conversation(conv_id)


def clear_recent_conversations() -> list[str]:
    """Archive all current recent conversations and return their ids."""
    archived_ids: list[str] = []
    for p in list(CONV_DIR.glob("*.json")):
        conv_id = p.stem
        try:
            if archive_conversation(conv_id):
                archived_ids.append(conv_id)
        except Exception:
            pass
    return archived_ids


def update_conversation_title(conv_id: str, new_title: str) -> bool:
    """Update a conversation's title."""
    conv = load_conversation(conv_id)
    if conv:
        conv["title"] = new_title
        save_conversation(conv_id, conv)
        return True
    return False
