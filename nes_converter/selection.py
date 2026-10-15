"""Unified modes use only input content; no sample IDs, policies, or targets."""
from .prompt import guard, v017, v019

CONTEXT_MODES = ("auto", "structured", "raw")
CONTRACT = "nes-unified-offline-context-v1"


def select_and_render(context: dict, *, context_mode: str) -> dict:
    if context_mode not in CONTEXT_MODES:
        raise ValueError(f"Unknown context mode: {context_mode!r}")
    if set(context) != guard.INPUT_FIELDS:
        raise v017.MappingSkip("INPUT_FIELDS_UNSUPPORTED", "Require only the accepted input fields")
    boundaries = guard.ambiguous_boundaries(context["related_context"])
    if context_mode == "structured" and boundaries:
        raise guard.ContextFidelityError(boundaries)
    raw = context_mode == "raw" or bool(boundaries)
    if raw:
        messages = v019.render_raw_context(context)
        representation = v019.CONTRACT
        reason = "EXPLICIT_RAW_CONTEXT" if context_mode == "raw" else "VERIFIED_CLOSED_LITERAL_HEADER_COLLISION"
    else:
        messages = v017.render_messages(v017.map_input(context))
        representation = v017.CONTRACT
        reason = "EXPLICIT_STRUCTURED_CONTEXT" if context_mode == "structured" else "NO_BOUNDED_LITERAL_HEADER_COLLISION"
    return {
        "messages": messages,
        "selection": {
            "requested_mode": context_mode, "context_mode": "raw" if raw else "structured",
            "reason": reason, "representation_contract": representation, "converter_contract": CONTRACT,
            "boundary_evidence": boundaries, "original_grouping_recovered": False,
            "scope": "Bounded closed non-interpolated assignment collision check; not a general parser proof",
        },
    }
