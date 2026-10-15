"""Versioned offline coordinate-domain adaptation; no inferred source-file offsets."""
import json
import re
from pathlib import Path

from ..errors import MappingSkip
from . import history

TEMPLATE = json.loads(Path(__file__).with_name('template.json').read_text(encoding='utf-8'))
CONTRACT = 'nes-explicit-coordinate-domains-v1'
STATUS = 'EXPLICIT_COORDINATE_DOMAIN_OFFLINE_NES_CANDIDATE'
SCHEMA = 'local-coordinate-domain-nes-candidates-v1'
DECLARATION = (
    'Coordinate domains for this example:\n'
    'Historical edit locations refer to their respective published past source-file snapshots. '
    'Their existing zero-based rendering does not rebase them to the current excerpt.\n'
    'Line numbers in current_file_content, cursor_location, and output patches are zero-based and local '
    'to the provided excerpt.\n'
    'No offset mapping between the historical source-file coordinate domains and this excerpt is known. '
    'Treat edit_diff_history as historical context, not as patches to apply to the current excerpt.'
)
PREFIX = DECLARATION + '\n\n'
FILE_REFERENCE = re.compile(r'<\|context_file\|> ([^\n]+)\n')


def map_snippets(text):
    history.prior.require(text.startswith(history.prior.SOURCE_PREFIX), 'Unknown source instruction/context framing')
    body = text[len(history.prior.SOURCE_PREFIX):]
    offset = 0
    references = []
    while (header := FILE_REFERENCE.match(body, offset)) and FILE_REFERENCE.match(body, header.end()):
        # The producer emits adjacent headers when the preceding reference has no supplied content.
        references.append({'path': header[1], 'lines': []})
        offset = header.end()
    return references + history.prior.map_snippets(history.prior.SOURCE_PREFIX + body[offset:])


def map_input(context):
    if set(context) != {'files', 'cursor', 'instruction', 'recent_history', 'related_context'}:
        raise MappingSkip('INPUT_FIELDS_UNSUPPORTED', 'Require the accepted native input-only schema')
    if context['instruction'] is not None or len(context['files']) != 1:
        raise MappingSkip('INPUT_SCOPE_UNSUPPORTED', 'Require one current excerpt and no separate instruction')
    try:
        entries = history.parse_history(context['recent_history'])
    except history.HistoryAmbiguity as exc:
        raise MappingSkip('SOURCE_HISTORY_EVIDENCE_REQUIRED', str(exc)) from exc
    path, text = next(iter(context['files'].items()))
    related = context['related_context']
    if related.startswith(history.prior.SOURCE_PREFIX) and not related[len(history.prior.SOURCE_PREFIX):].strip():
        snippets = []
    else:
        snippets = map_snippets(related)
    return {'path': path, 'lines': text.split('\n'), 'cursor': dict(context['cursor']),
            'snippets': snippets, 'history': [{'path': e['path'], 'hunks': e['hunks']} for e in entries]}


def base_messages(data):
    sections = history.prior.render_sections(data)
    sections['snippets'] = '\n\n'.join(
        '<|recently_viewed_code_snippet|>\ncode_snippet_file_path: ' + s['path'] + '\n'
        + '\n'.join(s['lines']) + '\n<|/recently_viewed_code_snippet|>' for s in data['snippets'])
    user = (
        f"<|recently_viewed_code_snippets|>\n{sections['snippets']}\n<|/recently_viewed_code_snippets|>\n\n"
        f"<|current_file_content|>\ncurrent_file_path: {data['path']}\n{sections['current']}\n"
        f"<|/current_file_content|>\n\n<|edit_diff_history|>\n{sections['history']}\n"
        f"<|/edit_diff_history|>\n\n<|cursor_location|>\n{sections['cursor']}\n<|/cursor_location|>"
        f"{TEMPLATE['postscript']}"
    ).strip()
    return [{'role': 'system', 'content': TEMPLATE['system']}, {'role': 'user', 'content': user}]


def render_messages(data):
    messages = base_messages(data)
    messages[1]['content'] = PREFIX + messages[1]['content']
    return messages


def adaptation():
    return {
        'version': CONTRACT, 'status': STATUS, 'schema': SCHEMA,
        'declaration': DECLARATION, 'placement': 'Prefix of every user message, outside code/history tags',
        'system_changed': False, 'postscript_changed': False, 'empty_label_convention_changed': False,
        'original_307_also_receive_declaration': True,
        'history_decoder': 'nes_converter.prompt.history',
        'inherited_formatting': [
            'Decode published historical hunk locations into the existing zero-based historical view, not excerpt positions',
            'Keep each change-group start in its historical base; use that start on both sides of the rendered header',
            'Reverse published newest-first history to oldest-first',
            'Render changed-line groups; omit unchanged hunk context and existing no-op/whitespace-only groups',
            'Omit history entries with no rendered hunks; preserve all source history in the accepted source',
            'Use unnumbered related code snippets in published order, not observed browsing order'],
        'new_history_filtering_or_truncation': False, 'inferred_offsets': False,
        'additional_source_format_support': (
            'Retain a leading header-only file reference with no supplied snippet content when followed '
            'immediately by another file header; this does not assert that the underlying file is empty'),
        'published_delimiters': 'Preserved source segmentation, not independent proof of original IDE snippet boundaries',
        'instruction_review': {
            'system': 'Predict next code edit subject to the unchanged policy constraints; no coordinate contract conflicts',
            'postscript': 'Output filename:line modified diffs and empty string for no candidate; declaration only fixes coordinate domains',
            'avoid_reverting_last_change': 'Preserved as an intent instruction, not interpreted as current-snapshot history replay',
            'source_rewrite_instruction': 'Removed only by the existing exact source-context parser, never global string replacement'},
        'upstream_template_equivalent': False, 'production_compatible': False,
        'training_ready': False, 'team_contract_confirmed': False, 'token_budget_verified': False}
