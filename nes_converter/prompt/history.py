"""Decode the published Instinct history grammar without rewriting source headers."""
import re
from . import text as prior


class HistoryAmbiguity(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise HistoryAmbiguity(message)


def parse_diff(text):
    lines = text.split('\n')
    starts = [i for i, line in enumerate(lines) if prior.HUNK.fullmatch(line)]
    need(bool(starts) and starts[0] == 0, 'No leading historical hunk header')
    blocks = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        match = prior.HUNK.fullmatch(lines[start])
        body = lines[start + 1:end]
        need(all(line and line[0] in ' +-' for line in body), 'Unknown historical body-line encoding')
        old_count = sum(line[0] != '+' for line in body)
        new_count = sum(line[0] != '-' for line in body)
        declared = (int(match[2] or 1), int(match[4] or 1))
        blocks.append({'header': lines[start], 'old_start': int(match[1]), 'new_start': int(match[3]),
                       'declared': declared, 'observed': (old_count, new_count), 'body': body,
                       'source_lines': (start, end)})
    strict = all(b['declared'] == b['observed'] for b in blocks)
    aggregate = (sum(not line.startswith('+') for line in lines[1:]),
                 sum(not line.startswith('-') for line in lines[1:]))
    reduced = not strict and len(blocks) > 1 and blocks[0]['declared'] == aggregate
    need(strict or reduced, 'Neither per-hunk counts nor the documented aggregate-first-header rule matches')
    if reduced:
        for index, block in enumerate(blocks[1:], 1):
            differences = tuple(d - o for d, o in zip(block['declared'], block['observed']))
            # The producer takes a contiguous slice through the final change, then trailing context.
            allowed_tail = index == len(blocks) - 1 and differences[0] == differences[1] >= 0
            need(block['declared'] == block['observed'] or allowed_tail,
                 'Interior hunk counts or final context-only trimming are inconsistent')
        last = blocks[-1]
        if last['declared'] != last['observed']:
            leading = next((i for i, line in enumerate(blocks[0]['body']) if line[0] != ' '),
                           len(blocks[0]['body']))
            trailing = next((i for i, line in enumerate(reversed(last['body'])) if line[0] != ' '),
                            len(last['body']))
            need(leading <= trailing, 'First/last context windows contradict a single producer slice')
    old_end = new_end = None
    hunks = []
    omitted = []
    for block in blocks:
        old_count, new_count = block['observed']
        old_pos = block['old_start'] - (1 if old_count else 0)
        new_pos = block['new_start'] - (1 if new_count else 0)
        need(old_pos >= 0 and new_pos >= 0, 'Negative historical source anchor')
        if old_end is not None:
            need(old_pos >= old_end and new_pos >= new_end, 'Overlapping/out-of-order historical hunks')
            need(old_pos - old_end == new_pos - new_end, 'Unexplained old/new coordinate gap between hunks')
        old_end, new_end = old_pos + old_count, new_pos + new_count
        group = None

        def flush():
            nonlocal group
            if group is not None:
                old, new = group['oldLines'], group['newLines']
                if old == new or not any(line.strip() for line in old + new):
                    omitted.append(group)
                else:
                    hunks.append(group)
                group = None

        for line in block['body']:
            prefix, value = line[0], line[1:]
            if prefix == ' ':
                flush()
                old_pos += 1
            else:
                if group is None:
                    group = {'startLineNumber': old_pos, 'oldLines': [], 'newLines': []}
                group['oldLines' if prefix == '-' else 'newLines'].append(value)
                old_pos += prefix == '-'
        flush()
    rebuilt = '\n'.join(part for block in blocks for part in [block['header'], *block['body']])
    need(rebuilt == text, 'Historical source roundtrip changed bytes')
    return {'hunks': hunks, 'blocks': blocks,
            'grammar': 'producer-aggregate-first-header' if reduced else 'per-hunk-unified',
            'aggregate_counts': aggregate, 'source_roundtrip': True,
            'omitted_by_existing_target_noop_whitespace_rule': omitted}


def parse_history(text):
    entries = []
    end = 0
    for match in prior.HISTORY_ENTRY.finditer(text):
        need(not text[end:match.start()].strip(), 'Unrecognized source history framing')
        parsed = parse_diff(match[2])
        entries.append({'path': match[1], 'hunks': parsed['hunks'], 'evidence': parsed,
                        'source_span': (match.start(), match.end()), 'raw_diff': match[2]})
        end = match.end()
    need(not text[end:].strip(), 'Unrecognized trailing source history')
    return entries
