"""Independent published-message span checks, not a producer or renderer roundtrip."""
import copy
import hashlib
import json
import re

from .patch import apply_patch

SYSTEM_SHA256 = "8e00cd4a314c79940f969da8b838be4345d18d90d04fa3586cc83badf44e58ec"
START = "<|editable_region_start|>"
END = "<|editable_region_end|>"
CURSOR = "<|user_cursor_is_here|>"


class SourceFidelityError(ValueError):
    def __init__(self, sample_id, field, detail, *, position=None, expected=None, observed=None):
        self.evidence = {"sample_id": sample_id, "field": field, "detail": detail,
                         "first_difference_codepoint": position, "expected": expected, "observed": observed}
        super().__init__(json.dumps(self.evidence, ensure_ascii=False))


def equal(sid, field, expected, observed):
    if expected == observed:
        return
    position = None
    if isinstance(expected, str) and isinstance(observed, str):
        position = next((i for i, pair in enumerate(zip(expected, observed)) if pair[0] != pair[1]),
                        min(len(expected), len(observed)))
        def excerpt(value):
            return {"characters": len(value), "near_difference": value[max(0, position - 40):position + 80],
                    "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        expected, observed = excerpt(expected), excerpt(observed)
    raise SourceFidelityError(sid, field, "Mismatch against independently extracted original message",
                              position=position, expected=expected, observed=observed)


def need(sid, field, condition, detail):
    if not condition:
        raise SourceFidelityError(sid, field, detail)


def normalized(sid, field, value):
    need(sid, field, isinstance(value, str), "Source message content must be a string")
    result = value.replace("\r\n", "\n")
    need(sid, field, not any(char in result for char in ("\r", "\v", "\f", "\x85", "\u2028", "\u2029")),
         "Only declared CRLF-to-LF normalization is supported")
    try:
        result.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SourceFidelityError(sid, field, "Unpaired Unicode surrogate") from error
    return result


def extract_published(source):
    """Use exact section/marker spans; no snippet splitter or native adapter calls."""
    sid = source["sample_id"]
    messages = source["row"]["messages"]
    equal(sid, "source.roles", ["system", "user", "assistant"], [m["role"] for m in messages])
    system, user, target = [normalized(sid, "source." + m["role"], m["content"]) for m in messages]
    equal(sid, "source.system_sha256", SYSTEM_SHA256, hashlib.sha256(system.encode("utf-8")).hexdigest())
    excerpt_tag = "### User Excerpt:\n"
    edit_tag = "### User Edits:\n"
    need(sid, "source.excerpt_boundary", user.count(excerpt_tag) == 1, "Require one exact excerpt section delimiter")
    excerpt_at = user.index(excerpt_tag)
    header = user[:excerpt_at]
    need(sid, "source.history_boundary", header.count(edit_tag) == 1,
         "Require one exact edits delimiter before the unique excerpt; ambiguous boundaries are not guessed")
    edits_at = header.index(edit_tag)
    related = user[:edits_at]
    history = user[edits_at + len(edit_tag):excerpt_at]
    excerpt = user[excerpt_at + len(excerpt_tag):]
    path_match = re.match(r'"([^"\n]+)"\n\n', excerpt)
    need(sid, "source.path", path_match is not None, "Require one quoted excerpt path and blank separator")
    path = path_match[1]
    need(sid, "source.path", path.endswith(".ts") and not path.startswith(("+", "-")),
         "Pinned source contract supports a plain .ts path")
    marked = excerpt[path_match.end():]
    for token in (START, END, CURSOR):
        need(sid, "source.marker_count", marked.count(token) == 1, f"Require exactly one declared {token} marker")
    start_match = re.search(r"(?m)^" + re.escape(START) + r"\n", marked)
    end_match = re.search(r"(?m)^" + re.escape(END) + r"(?:\n|$)", marked)
    need(sid, "source.region_layout", start_match is not None and end_match is not None,
         "Region markers must occupy full lines")
    need(sid, "source.region_order", start_match.end() <= end_match.start(), "Region boundaries reversed")
    prefix = marked[:start_match.start()]
    region = marked[start_match.end():end_match.start()]
    suffix = marked[end_match.end():]
    need(sid, "source.cursor_span", CURSOR in region, "Declared cursor must be within the editable region")
    # The LF immediately before the end delimiter separates region lines from that delimiter.
    need(sid, "source.region_layout", region.endswith("\n"), "Missing end-delimiter line boundary")
    region = region[:-1]
    marked_code = prefix + region + ("\n" + suffix if end_match[0].endswith("\n") else "")
    cursor_at = marked_code.index(CURSOR)
    before = marked_code[:cursor_at] + marked_code[cursor_at + len(CURSOR):]
    preceding = marked_code[:cursor_at]
    column = preceding[preceding.rfind("\n") + 1:]
    cursor = {"line_zero_based": preceding.count("\n"), "column_codepoints_zero_based": len(column),
              "column_utf16_units_zero_based": len(column.encode("utf-16-le")) // 2}
    need(sid, "source.assistant", bool(target), "Empty serialized region rewrite is ambiguous")
    need(sid, "source.assistant", not any(token in target for token in (START, END, CURSOR)),
         "Assistant contains a reserved source control marker")
    after = prefix + target + ("\n" + suffix if end_match[0].endswith("\n") else "")
    return {
        "input_context": {"files": {path: before}, "cursor": cursor, "instruction": None,
                          "related_context": related, "recent_history": history},
        "expected_result": {path: after},
        "spans": {"coordinate_domain": "normalized-user codepoints",
                  "related_context": [0, edits_at],
                  "history": [edits_at + len(edit_tag), excerpt_at],
                  "excerpt": [excerpt_at + len(excerpt_tag), len(user)]},
    }


def verify_original(canonical, source):
    sid = canonical["id"]
    extracted = extract_published(source)
    observed = canonical["input_context"]
    equal(sid, "input.fields", sorted(extracted["input_context"]), sorted(observed))
    for field in ("related_context", "recent_history", "cursor", "instruction"):
        equal(sid, "input." + field, extracted["input_context"][field], observed[field])
    equal(sid, "input.file_paths", list(extracted["input_context"]["files"]), list(observed["files"]))
    for path, content in extracted["input_context"]["files"].items():
        equal(sid, "input.files." + path, content, observed["files"][path])
    equal(sid, "target.file_paths", list(extracted["expected_result"]), list(canonical["expected_result"]))
    for path, content in extracted["expected_result"].items():
        equal(sid, "target.expected_after." + path, content, canonical["expected_result"][path])
    try:
        applied = apply_patch(extracted["input_context"]["files"], canonical["patch"])
    except ValueError as error:
        raise SourceFidelityError(sid, "target.patch", str(error)) from error
    equal(sid, "target.patch_result", extracted["expected_result"], applied)
    return extracted


def alternate_target_input(source):
    altered = copy.deepcopy(source)
    altered["row"]["messages"][2]["content"] = "/* independent valid alternative target */"
    return extract_published(altered)["input_context"]
