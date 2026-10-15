"""Existing native-adapter text rules; no new normalization policy."""
from .errors import Rejection

START = "<|editable_region_start|>"
END = "<|editable_region_end|>"
CURSOR = "<|user_cursor_is_here|>"
TOKENS = (START, END, CURSOR)


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n")
    if any(char in text for char in ("\r", "\v", "\f", "\x85", "\u2028", "\u2029")):
        raise Rejection("EOL_UNSUPPORTED", "Only LF and CRLF are supported")
    return text


def eol_metadata(texts: list[str]) -> dict:
    crlf = sum(text.count("\r\n") for text in texts)
    bare_lf = sum(text.count("\n") - text.count("\r\n") for text in texts)
    return {"policy": "LF canonical; CRLF normalized; other line separators rejected",
            "crlf_sequences": crlf, "bare_lf_sequences": bare_lf,
            "mixed_lf_crlf": bool(crlf and bare_lf), "normalization_performed": bool(crlf),
            "exact_original_file_bytes_claimed": False,
            "raw_source_preserved_in_original_record": True}
