"""Fail closed on evidenced literal/framing collisions; never guess original ownership."""
import json
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from ..runtime import require, run_node
from . import v017 as previous

SYNTAX_INSPECTOR = Path(__file__).parent.parent / "validation" / "inspect_quotes.cjs"
CONTRACT = "nes-related-context-fidelity-guard-v1"
INPUT_FIELDS = {"files", "cursor", "instruction", "recent_history", "related_context"}
ASSIGNMENT = re.compile(
    r'(?m)^[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*'
    r'(`(?:\\[\s\S]|[^`\\])*`|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')[ \t]*;'
)


class ContextFidelityError(ValueError):
    code = "RELATED_CONTEXT_BOUNDARY_NONINJECTIVE"

    def __init__(self, boundaries):
        self.boundaries = boundaries
        super().__init__(
            f"{self.code}: {len(boundaries)} complete literal assignment(s) contain prospective "
            "snippet boundaries. The published format does not distinguish literal body from framing. "
            "Do not promote these headers or guess file ownership. Require producer-side boundary evidence "
            "or an explicitly approved raw-context representation. This is not a dataset exclusion."
        )


@lru_cache(maxsize=256)
def syntax_evidence(statement):
    parsed = run_node(SYNTAX_INSPECTOR, [{"sha256": text_hash(statement), "statement": statement}])
    require(parsed["typescript"] == "5.9.3", "Syntax checker version changed")
    require(len(parsed["results"]) == 1, "Invalid syntax checker response")
    evidence = parsed["results"][0]
    require(evidence["sha256"] == text_hash(statement), "Syntax checker input mismatch")
    return evidence


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ambiguous_boundaries(text):
    prefix = previous.history.prior.SOURCE_PREFIX
    if not text.startswith(prefix):
        raise previous.MappingSkip("INPUT_CONTEXT_FRAMING_UNSUPPORTED", "Require the exact source context prefix")
    body = text[len(prefix):]
    boundaries = []
    for assignment in ASSIGNMENT.finditer(body):
        if "${" in assignment[2]:
            continue
        headers = list(previous.history.prior.CONTEXT_HEADER.finditer(
            body, assignment.start(2), assignment.end(2)
        ))
        if not headers:
            continue
        syntax = syntax_evidence(assignment[0])
        if not syntax["validClosedStringAssignment"]:
            continue
        boundaries.append({
            "statement_sha256": text_hash(assignment[0]),
            "statement_start": len(prefix) + assignment.start(),
            "statement_end": len(prefix) + assignment.end(),
            "offset_domain": "Python code-point offsets in full published related_context",
            "prospective_headers": [
                {"start": len(prefix) + header.start(), "end": len(prefix) + header.end(), "path_text": header[1]}
                for header in headers
            ],
            "syntax": syntax,
            "original_owner": None,
        })
    return boundaries


def guard_related_context(text):
    boundaries = ambiguous_boundaries(text)
    if boundaries:
        raise ContextFidelityError(boundaries)


def map_snippets(text):
    guard_related_context(text)
    return previous.map_snippets(text)


def map_input(context):
    if set(context) != INPUT_FIELDS:
        raise previous.MappingSkip("INPUT_FIELDS_UNSUPPORTED", "Require the accepted native input-only schema")
    guard_related_context(context["related_context"])
    return previous.map_input(context)


def render_input(context):
    return previous.render_messages(map_input(context))
