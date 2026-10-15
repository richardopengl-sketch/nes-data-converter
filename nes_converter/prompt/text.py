"""Input-only, bounded Instinct mapping and pinned-source NES text renderer."""
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SOURCE_PREFIX = (
    "Reference the user excerpt, user edits, and the snippets to understand the developer's intent. "
    "Update the editable region of the user excerpt by predicting and completing the changes they "
    "would have made next. This may be a deletion, addition, or modification of code.\n\n"
    "### Context:\n\n"
)
CONTEXT_HEADER = re.compile(r'(?m)^<\|context_file\|> ([^\n]+)\n<\|snippet\|>\n')
HISTORY_ENTRY = re.compile(r'User edited file "([^"\n]+)"\n\n```diff\n(.*?)\n```', re.DOTALL)
HUNK = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def map_snippets(text: str) -> list[dict[str, Any]]:
    require(text.startswith(SOURCE_PREFIX), 'Unknown source instruction/context framing')
    body = text[len(SOURCE_PREFIX):]
    headers = list(CONTEXT_HEADER.finditer(body))
    require(bool(headers) and headers[0].start() == 0, 'Missing first context snippet header')
    snippets = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        # Retain every published payload character, including boundary blank lines.
        payload = body[match.end():end]
        snippets.append({'path': match[1], 'lines': payload.split('\n')})
    return snippets


def changed_hunks(diff: str) -> list[dict[str, Any]]:
    lines = diff.split('\n')
    result = []
    i = 0
    while i < len(lines):
        header = HUNK.fullmatch(lines[i])
        require(header is not None, f'Unsupported historical hunk header at line {i}')
        assert header is not None
        old_start, old_count = int(header[1]), int(header[2] or 1)
        new_count = int(header[4] or 1)
        old_position = old_start - 1 if old_count else old_start
        require(old_position >= 0, 'Invalid historical old start')
        old_seen = new_seen = 0
        pending: dict[str, Any] | None = None

        def flush() -> None:
            nonlocal pending
            if pending is not None:
                old, new = pending['oldLines'], pending['newLines']
                if old != new and any(line.strip() for line in old + new):
                    result.append(pending)
                pending = None

        i += 1
        while i < len(lines) and not lines[i].startswith('@@ '):
            line = lines[i]
            require(bool(line) and line[0] in ' +-',
                    f'Unsupported historical diff line at {i}')
            sign, content = line[0], line[1:]
            if sign == ' ':
                flush()
                old_position += 1
                old_seen += 1
                new_seen += 1
            else:
                if pending is None:
                    pending = {'startLineNumber': old_position, 'oldLines': [], 'newLines': []}
                pending['oldLines' if sign == '-' else 'newLines'].append(content)
                if sign == '-':
                    old_position += 1
                    old_seen += 1
                else:
                    new_seen += 1
            i += 1
        flush()
        require((old_seen, new_seen) == (old_count, new_count),
                f'Historical hunk counts disagree: {(old_seen, new_seen)} != {(old_count, new_count)}')
    return result


def map_history(text: str) -> list[dict[str, Any]]:
    result = []
    end = 0
    for match in HISTORY_ENTRY.finditer(text):
        require(not text[end:match.start()].strip(), 'Unrecognized text between history entries')
        result.append({'path': match[1], 'hunks': changed_hunks(match[2])})
        end = match.end()
    require(not text[end:].strip(), 'Unrecognized trailing history')
    return result


def map_input(context: dict[str, Any]) -> dict[str, Any]:
    require(set(context) == {'files', 'cursor', 'instruction', 'recent_history', 'related_context'},
            'Input context contains missing/unapproved fields')
    require(context['instruction'] is None, 'Unexpected separate source instruction')
    require(len(context['files']) == 1, 'Pilot requires exactly one current excerpt')
    path, before = next(iter(context['files'].items()))
    return {
        'path': path, 'lines': before.split('\n'), 'cursor': dict(context['cursor']),
        'snippets': map_snippets(context['related_context']),
        'history': map_history(context['recent_history']),
    }


def numbered(lines: list[str]) -> str:
    return '\n'.join(f'{i}|{line}' for i, line in enumerate(lines))


def render_sections(data: dict[str, Any]) -> dict[str, str]:
    require(set(data) == {'path', 'lines', 'cursor', 'snippets', 'history'},
            'Renderer accepts only mapped input fields')
    cursor = data['cursor']
    row = cursor['line_zero_based']
    cp = cursor['column_codepoints_zero_based']
    require(0 <= row < len(data['lines']), 'Cursor row outside excerpt')
    line = data['lines'][row]
    require(0 <= cp <= len(line), 'Cursor column outside line')
    require(len(line[:cp].encode('utf-16-le')) // 2 == cursor['column_utf16_units_zero_based'],
            'Codepoint and UTF-16 cursor disagree')
    snippets = '\n\n'.join(
        f"<|recently_viewed_code_snippet|>\ncode_snippet_file_path: {s['path']}\n"
        f"{numbered(s['lines'])}\n<|/recently_viewed_code_snippet|>" for s in data['snippets'])
    diffs = []
    for entry in reversed(data['history']):
        if not entry['hunks']:
            continue
        parts = [f"--- {entry['path']}", f"+++ {entry['path']}"]
        for hunk in entry['hunks']:
            start = hunk['startLineNumber']
            old, new = hunk['oldLines'], hunk['newLines']
            parts.append(f'@@ -{start},{len(old)} +{start},{len(new)} @@')
            parts.extend('-' + text for text in old)
            parts.extend('+' + text for text in new)
        diffs.append('\n'.join(parts))
    return {
        'snippets': snippets,
        'current': numbered(data['lines']),
        'history': '\n\n'.join(diffs) + ('\n' if diffs else ''),
        'cursor': f'{row}|{line[:cp]}<|cursor|>{line[cp:]}',
    }


def render_messages(data: dict[str, Any]) -> list[dict[str, str]]:
    template = json.loads((ROOT / 'template.json').read_text(encoding='utf-8'))
    sections = render_sections(data)
    user = (
        f"<|recently_viewed_code_snippets|>\n{sections['snippets']}\n<|/recently_viewed_code_snippets|>\n\n"
        f"<|current_file_content|>\ncurrent_file_path: {data['path']}\n{sections['current']}\n"
        f"<|/current_file_content|>\n\n<|edit_diff_history|>\n{sections['history']}\n"
        f"<|/edit_diff_history|>\n\n<|cursor_location|>\n{sections['cursor']}\n<|/cursor_location|>"
        f"{template['postscript']}"
    ).strip()
    return [{'role': 'system', 'content': template['system']}, {'role': 'user', 'content': user}]
