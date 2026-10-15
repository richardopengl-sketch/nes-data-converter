"""Interpret the declared published-message contract, not unknown pre-render editor bytes."""
import hashlib
import re

from .errors import Rejection
from .schema import Canonical
from .validation.instinct_lexical import inspect_cursor
from .source_text import CURSOR, END, START, TOKENS, eol_metadata, normalize

REVISION = "e557e3ed1ea2c28b9c6b7cc46d670aa3cd451c29"
SYSTEM_SHA256 = "8e00cd4a314c79940f969da8b838be4345d18d90d04fa3586cc83badf44e58ec"


def adapt(record: dict) -> Canonical:
    if record.get("revision") != REVISION:
        raise Rejection("SOURCE_RELEASE_UNSUPPORTED", "Native support is bounded to the pinned published release")
    if record.get("viewer_revision_verified") is not True:
        raise Rejection("SOURCE_REVISION_UNVERIFIED", "Retained download receipt does not verify the release revision")
    messages = record["row"]["messages"]
    if [message["role"] for message in messages] != ["system", "user", "assistant"]:
        raise Rejection("MESSAGE_ROLES", "Require system, user, assistant")
    system, user, target = [normalize(message["content"]) for message in messages]
    try:
        for text in (system, user, target):
            text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise Rejection("SOURCE_UNICODE_UNSUPPORTED", "Unpaired Unicode surrogates are unsupported") from exc
    if hashlib.sha256(system.encode()).hexdigest() != SYSTEM_SHA256:
        raise Rejection("SOURCE_SYSTEM_CONTRACT", "The published cursor/region declaration must match the pinned producer")
    heading = "### User Excerpt:\n"
    if user.count(heading) != 1:
        raise Rejection("EXCERPT_HEADING", "Require one excerpt section")
    context_header, excerpt = user.split(heading)
    history_heading = "### User Edits:\n"
    if context_header.count(history_heading) != 1:
        raise Rejection("HISTORY_HEADING", "Require one history section")
    related, history = context_header.split(history_heading)
    path_line, separator, marked = excerpt.partition("\n\n")
    if not separator or not re.fullmatch(r'"[^"\n]+"', path_line):
        raise Rejection("PATH_LAYOUT", "Require one quoted excerpt path")
    path = path_line[1:-1]
    if not path.endswith(".ts") or path.startswith(("+", "-")):
        raise Rejection("NATIVE_PATH_UNSUPPORTED", "This contract supports plain .ts excerpts only")
    if marked.count(START) != 1 or marked.count(END) != 1:
        raise Rejection("REGION_MARKER_COUNT", "Require unique region markers; do not strip collisions")
    lines = marked.split("\n")
    if START not in lines or END not in lines:
        raise Rejection("REGION_DELIMITER_LAYOUT", "Region markers must occupy their own lines")
    start, end = lines.index(START), lines.index(END)
    if start >= end:
        raise Rejection("REGION_MARKER_ORDER", "Region start must precede its end")
    if marked.count(CURSOR) != 1:
        raise Rejection("CURSOR_COUNT", "Native declared-cursor subset requires exactly one cursor")
    prefix, region, suffix = lines[:start], lines[start + 1:end], lines[end + 1:]
    if CURSOR not in "\n".join(region):
        raise Rejection("CURSOR_OUTSIDE_REGION", "Cursor must occur inside the declared editable region")
    if target == "":
        raise Rejection("EMPTY_TARGET_AMBIGUOUS", "Joined zero lines and one empty line are indistinguishable")
    if any(token in target for token in TOKENS):
        raise Rejection("TARGET_CONTROL_MARKER", "Never strip reserved tokens from the assistant target")
    marked_code = "\n".join(prefix + region + suffix)
    offset = marked_code.index(CURSOR)
    lexical = inspect_cursor(marked_code, offset)
    if not lexical["supported"]:
        raise Rejection(lexical["reason"], lexical["detail"])
    before = marked_code[:offset] + marked_code[offset + len(CURSOR):]
    after = "\n".join(prefix + target.split("\n") + suffix)
    preceding = before[:offset]
    column = preceding.rsplit("\n", 1)[-1]
    cursor = {"line_zero_based": preceding.count("\n"),
              "column_codepoints_zero_based": len(column),
              "column_utf16_units_zero_based": len(column.encode("utf-16-le")) // 2}
    return Canonical(
        {"files": {path: before}, "cursor": cursor, "recent_history": history,
         "related_context": related, "instruction": None},
        {path: after},
        {"source_adapter": {
            "contract": "instinct-native-published-v1", "source_system_sha256": SYSTEM_SHA256,
            "cursor_status": "declared_by_published_system_message",
            "eol": eol_metadata([message["content"] for message in messages]),
            "region_start_line_zero_based": len(prefix), "region_line_count": len(region),
            "history_order": "most_recent_first_as_published",
            "typescript_lexical_guard": lexical["typescript_version"],
            "target_interpretation": "published joined region lines; replace only this region"},
         "source_fidelity_scope": "published_message_excerpt",
         "official_split": record["split"],
         "evaluation_role": "validation-only" if record["split"] == "test_typescript" else "train-candidate",
         "original_editor_snapshot_verified": False, "renderer_run_configuration_verified": False,
         "coordinate_space": "excerpt_local", "synthetic_path": False, "original_file_offset": None,
         "nes_ready": False,
         "limitations": ["Published-message interpretation, not an injective inverse of every renderer configuration",
                         "Original editor bytes and excerpt initial lexical state are not independently available",
                         "Only token-boundary cursors outside observable literals/comments are supported",
                         "No verified global offset or production input serialization"]})
