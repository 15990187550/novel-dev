from __future__ import annotations

from typing import Any


INTERNAL_ENTITY_STATE_KEYS = {
    "_merged_duplicate_entities",
}


def sanitize_entity_state_for_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_entity_state_for_context(item)
            for key, item in value.items()
            if str(key) not in INTERNAL_ENTITY_STATE_KEYS
        }
    if isinstance(value, list):
        return [sanitize_entity_state_for_context(item) for item in value]
    return value
