"""Explicit independent candidate mode; never replaces the existing main mapper."""
from . import guard
from . import v017 as previous

CONTRACT = "nes-opaque-canonical-related-context-v1"
STATUS = "INDEPENDENT_OPAQUE_RELATED_CONTEXT_CANDIDATE"
OPEN = "<|recently_viewed_code_snippets|>\n"
CLOSE = "\n<|/recently_viewed_code_snippets|>"
BEGIN = "-----BEGIN OPAQUE RELATED CONTEXT-----"
END = "-----END OPAQUE RELATED CONTEXT-----"
NOTICE = (
    "The following block is the complete published related context after the dataset adapter's "
    "existing CRLF-to-LF normalization. Its file/snippet markers are source text, not a verified "
    "mapping of payloads to files. No original snippet boundaries, file offsets, or browsing "
    "order are inferred."
)


def render_raw_context(context):
    if set(context) != guard.INPUT_FIELDS:
        raise previous.MappingSkip("INPUT_FIELDS_UNSUPPORTED", "Require the input-only canonical schema")
    prefix = previous.history.prior.SOURCE_PREFIX
    related = context["related_context"]
    if not related.startswith(prefix):
        raise ValueError("Unrecognized source-task prefix; do not infer or strip context framing")
    body = related[len(prefix):]
    for delimiter in (BEGIN, END, OPEN.rstrip("\n"), CLOSE.lstrip("\n")):
        if delimiter in body:
            raise ValueError(f"Opaque wrapper collision: {delimiter!r}; no escaping or truncation applied")

    # Reuse all v017 non-context mapping; insert the untouched body separately below.
    base_context = {**context, "related_context": prefix}
    messages = previous.render_messages(previous.map_input(base_context))
    empty_prefix = previous.PREFIX + OPEN + CLOSE
    if not messages[1]["content"].startswith(empty_prefix):
        raise ValueError("Pinned empty-context template differs; refusing to splice an unknown message")
    new_prefix = previous.PREFIX + OPEN + NOTICE + "\n\n" + BEGIN + "\n" + body + "\n" + END + CLOSE
    messages[1]["content"] = new_prefix + messages[1]["content"][len(empty_prefix):]
    return messages


def render_independent_candidate(context):
    if set(context) != guard.INPUT_FIELDS:
        raise previous.MappingSkip("INPUT_FIELDS_UNSUPPORTED", "Require the input-only canonical schema")
    boundaries = guard.ambiguous_boundaries(context["related_context"])
    if boundaries:
        return {
            "representation": CONTRACT, "messages": render_raw_context(context),
            "generated_file_associations": [], "original_grouping_recovered": False,
        }
    return {
        "representation": previous.CONTRACT, "messages": guard.render_input(context),
        "original_grouping_recovered": False,
    }
