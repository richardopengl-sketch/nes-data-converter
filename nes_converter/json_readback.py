"""Verify loaded model messages with one inner JSON parse; never call the encoder."""
import json

from .batch import object_hash
from .prompt import v017, v019
from .prompt.json_context import CONTRACT, NOTICE
from .prompt.text import SOURCE_PREFIX
from .runtime import require


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON payload key: {key}")
        result[key] = value
    return result


def verify_visible_messages(messages, expected_context, *, expected_messages_hash):
    """expected_context must be independently source-checked, never decoded from this payload."""
    require([message["role"] for message in messages] == ["system", "user"], "Expected exactly System/User")
    require(all(set(message) == {"role", "content"} and isinstance(message["content"], str)
                for message in messages), "Unexpected model-message fields or content type")
    require(object_hash(messages) == expected_messages_hash, "Loaded JSONL messages differ from pre-export messages")
    related = expected_context["related_context"]
    require(related.startswith(SOURCE_PREFIX), "Missing fixed source prefix in independent expectation")
    expected_body = related[len(SOURCE_PREFIX):]
    base = v017.render_messages(v017.map_input({**expected_context, "related_context": SOURCE_PREFIX}))
    require(messages[0] == base[0], "System changed")
    empty_start = v017.PREFIX + v019.OPEN + v019.CLOSE
    require(base[1]["content"].startswith(empty_start), "Pinned empty-context framing changed")
    start = v017.PREFIX + v019.OPEN + NOTICE + "\n"
    user = messages[1]["content"]
    require(user.startswith(start), "Missing declared experimental User prefix")
    value, end = json.JSONDecoder(object_pairs_hook=_unique_fields).raw_decode(user, len(start))
    require(isinstance(value, dict) and list(value) == ["schema", "text"], "Unexpected JSON payload fields/order")
    require(value["schema"] == CONTRACT and isinstance(value["text"], str), "Wrong schema or body type")
    payload = user[len(start):end]
    require(payload.isascii() and "\n" not in payload and "\r" not in payload, "Payload is not single-line ASCII JSON")
    require("<" not in payload and ">" not in payload, "Unencoded angle bracket in serialized body")
    require(user[end:] == v019.CLOSE + base[1]["content"][len(empty_start):],
            "Payload boundary or current code/history/cursor/output instructions changed")
    require(value["text"] == expected_body, "One decoded body differs from independently checked context")
    require(value["text"].encode("utf-8") == expected_body.encode("utf-8"), "Decoded UTF-8 bytes differ")
    return {
        "payload": payload, "decoded_body": value["text"], "inner_json_decode_calls": 1,
        "outer_jsonl_messages_exact": True, "one_decode_source_body_exact": True,
        "system_unchanged": True, "non_context_user_unchanged": True,
        "serialized_payload_has_no_original_outer_tags": True,
    }
