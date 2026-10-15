"""Read-only TypeScript collision guard; this is not marker-origin evidence."""
from pathlib import Path

from ..errors import VerificationError
from ..runtime import run_node


def inspect_cursor(text: str, cursor_codepoints: int) -> dict:
    offset = len(text[:cursor_codepoints].encode("utf-16-le")) // 2
    script = Path(__file__).with_name("instinct_lexical.cjs")
    report = run_node(script, {"text": text, "offset": offset})
    if not isinstance(report, dict) or type(report.get("supported")) is not bool:
        raise VerificationError("instinct_lexical", "Malformed TypeScript guard response")
    return report
