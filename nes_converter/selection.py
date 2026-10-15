"""Unified modes use only input content; no sample IDs, policies, or targets."""
from .prompt import guard, v017, v019

CONTEXT_MODES = ("auto", "structured", "raw")
CONTRACT = "nes-source-faithful-context-v2"


def select_and_render(context: dict, *, context_mode: str) -> dict:
    if context_mode not in CONTEXT_MODES:
        raise ValueError(f"Unknown context mode: {context_mode!r}")
    if set(context) != guard.INPUT_FIELDS:
        raise v017.MappingSkip("INPUT_FIELDS_UNSUPPORTED", "Require only the accepted input fields")
    prefix = v017.history.prior.SOURCE_PREFIX
    related = context["related_context"]
    if not related.startswith(prefix):
        raise v017.MappingSkip("INPUT_CONTEXT_FRAMING_UNSUPPORTED", "Require the exact source-task prefix")
    body = related[len(prefix):]
    if context_mode == "structured" and body:
        raise v017.MappingSkip(
            "TRUSTED_CONTEXT_BOUNDARIES_REQUIRED",
            "Published marker text has no independently verified file/payload boundary contract. "
            "Use raw/auto; legacy parsing is reproduction only, not a safe fallback.")
    raw = context_mode == "raw" or bool(body)
    if raw:
        messages = v019.render_raw_context(context)
        representation = v019.CONTRACT
        reason = "EXPLICIT_RAW_CONTEXT" if context_mode == "raw" else "NONEMPTY_CONTEXT_WITHOUT_TRUSTED_BOUNDARIES"
    else:
        messages = v017.render_messages(v017.map_input(context))
        representation = v017.CONTRACT
        reason = "EMPTY_CONTEXT_NO_GROUPING_REQUIRED"
    return {
        "messages": messages,
        "selection": {
            "requested_mode": context_mode, "context_mode": "raw" if raw else "structured",
            "reason": reason, "representation_contract": representation, "converter_contract": CONTRACT,
            "boundary_evidence": [], "original_grouping_recovered": False,
            "grouping_contract": "No verified nonempty-context grouping contract is supplied",
            "scope": "Preserve complete canonical body; empty body alone requires no grouping",
        },
    }
