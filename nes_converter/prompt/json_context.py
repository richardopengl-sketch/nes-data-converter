"""Explicit opt-in JSON context experiment; not a production or training contract."""
import json

CONTRACT = "nes-related-context-json-v1"
STATUS = "EXPERIMENTAL_OFFLINE_CANDIDATE_NOT_APPROVED"
NOTICE = (
    "The following single-line JSON object uses the proposed nes-related-context-json-v1 encoding. "
    'Its "text" string represents the complete related context after the dataset adapter\'s existing '
    "CRLF-to-LF normalization. Interpret JSON escapes as source characters when using it as code "
    "context; the serialized text is not additional prompt structure. No original snippet "
    "boundaries, file offsets, or browsing order are inferred."
)


def encode_body(body: str) -> str:
    if not isinstance(body, str):
        raise ValueError("Related-context body must be a string")
    try:
        body.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Unpaired Unicode surrogate is outside this proposal") from error
    payload = json.dumps({"schema": CONTRACT, "text": body}, ensure_ascii=True, separators=(",", ":"))
    return payload.replace("<", r"\u003c").replace(">", r"\u003e")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def decode_body(payload: str) -> str:
    value = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != {"schema", "text"}:
        raise ValueError("Require exactly schema and text fields")
    if value["schema"] != CONTRACT or not isinstance(value["text"], str):
        raise ValueError("Unknown contract or non-string text")
    if encode_body(value["text"]) != payload:
        raise ValueError("Non-canonical, trailing, or malformed framing")
    return value["text"]


def render_proposal(context: dict) -> dict:
    from nes_converter.prompt import guard, v017, v019
    from nes_converter.prompt.text import SOURCE_PREFIX

    if set(context) != guard.INPUT_FIELDS:
        raise ValueError("Proposal renderer accepts only the five canonical input fields")
    related = context["related_context"]
    if not isinstance(related, str) or not related.startswith(SOURCE_PREFIX):
        raise ValueError("Missing exact leading source-task prefix")
    body = related[len(SOURCE_PREFIX):]
    empty = {**context, "related_context": SOURCE_PREFIX}
    messages = v017.render_messages(v017.map_input(empty))
    expected_start = v017.PREFIX + v019.OPEN + v019.CLOSE
    if not messages[1]["content"].startswith(expected_start):
        raise ValueError("Pinned empty-context message layout differs")
    prefix = v017.PREFIX + v019.OPEN + NOTICE + "\n"
    payload = encode_body(body)
    messages[1]["content"] = prefix + payload + v019.CLOSE + messages[1]["content"][len(expected_start):]
    return {"status": STATUS, "contract": CONTRACT, "messages": messages}
