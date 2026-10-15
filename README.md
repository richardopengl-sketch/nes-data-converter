# Unified NES converter

**Source-fidelity repair:** based on
`21d305d86830451aef735e28f175ed72ffe99f1e`. This revision changes both the
context selector and original-source checker; it is not a production or
training-contract approval.

Source-only repository: **[richardopengl-sketch/nes-data-converter](https://github.com/richardopengl-sketch/nes-data-converter)**.
The user requested publication to this personal GitHub account; repository visibility was
verified as public for this update and was not changed by the update. Only the reviewed source, synthetic tests, configuration and documentation are
included. Real samples and full offline candidate packages remain outside Git.
Publication does not approve a production/training input contract or further redistribution.

## Scope and mode selection

The unified `convert` and `batch` commands require one explicit `--context-mode`:

| Context mode | Behavior |
|---|---|
| `structured` | Only an exactly empty context body is supported. Nonempty published text lacks an independently verified grouping contract and fails explicitly. |
| `raw` | Retain the entire canonical context body as opaque source text; no guessed grouping or file associations. Does not require collision classification. Wrapper collisions fail. |
| `auto` | Nonempty body (including whitespace) uses raw. Exactly empty body needs no grouping and uses the empty structured representation. No ID list, syntax detector, filename allowlist or target information. |

The unified converter assembles complete offline views using `auto`. Historical
behavior is separately available through the legacy `render --mode` command:

| Explicit mode | Preserved behavior |
|---|---|
| `v017-structured` | Historical coordinate-domain adaptation, including the known related-context literal-splitting defect. Reproduction only; v017 is not relabeled as fixed. |
| `v018-guarded` | Same structured representation; raises a diagnostic for the bounded literal/framing collision. A diagnostic is not a dataset exclusion. |
| `v019-independent` | Explicit opt-in candidate. Retains the complete opaque canonical context on the same detected cases; otherwise returns the unchanged structured messages. Does not infer original groups. |

**There is no implicit mode.** The new unified converter integrates v019's raw preservation
into a complete offline package, without modifying historical v017/v019 releases. It does
not change labels, expected after, roles, membership policies or the production/training
contract. Real records and full output packages are intentionally not in this source tree.

## Prerequisites and a clean source checkout

- Python 3.12 or newer; tested here with Python 3.12.10. Runtime uses only the standard library.
- Node.js 18 or newer; tested here with Node.js 24.21.0. Other versions are not certified.
- TypeScript **5.9.3**, pinned in the npm lockfile, is used only to parse text, never execute it.
- Optional Python build uses setuptools **84.0.0**. Source-tree usage requires no pip install.

With repository access, clone and run from its root:

The following clone command retrieves the current published main branch. Record
`git rev-parse HEAD` when reviewing or reproducing a result. Installation instructions
describe an approved checkout workflow; no installation was executed during this repair.

```text
git clone https://github.com/richardopengl-sketch/nes-data-converter.git
cd nes-data-converter
npm ci --ignore-scripts --registry=https://registry.npmjs.org
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m nes_converter --help
```

These tests are synthetic and include native-source adaptation, patch replay, complete
messages, mode differences, target isolation, cursor Unicode, history, opaque-body
preservation and CLI errors. No dataset, tokenizer, model, credentials or GPU is needed.
Do not point the environment at old revisions to make imports work; all source imports
and runtime helpers are included here.

An existing independently installed TypeScript 5.9.3 can be selected with
`NES_TYPESCRIPT_MODULE` (its module directory), for offline validation without installing.
The normal clone workflow uses repository-local `node_modules` from `npm ci`.
No user-specific path is embedded. Node is resolved from `PATH`.

Registry access in the preparation environment was blocked by policy/TLS failure. No
installation or certificate bypass was performed. The lockfile pins the existing verified
5.9.3 package integrity and uses its standard public registry URL; a fresh network `npm ci`
has **not** been verified here. Use an approved network or the explicit existing-module
option; do not bypass organizational restrictions.

## Input and output

The input-only renderer requires exactly:

```json
{
  "files": {"demo.ts": "let count = 1;"},
  "cursor": {
    "line_zero_based": 0,
    "column_codepoints_zero_based": 14,
    "column_utf16_units_zero_based": 14
  },
  "instruction": null,
  "recent_history": "",
  "related_context": "Exact source-task prefix followed by published related context"
}
```

This field sketch is **not a runnable data example**: use the synthetic fixtures in
[the tests](tests/test_handoff.py), which construct the exact fixed prefix. Real records
must already have the source provenance and interpretation required by the native adapter.

```text
python -B -m nes_converter adapt --input private-source.json --output private-canonical.json
python -B -m nes_converter convert --context-mode auto --input private-input-only.json --output private-messages.json
```

`adapt` accepts one source wrapper containing dataset, pinned revision, verified provenance
flag, sample ID, split, and the original `row.messages`. It produces input context, unchanged
source-derived expected result, assistant patch and metadata separately. An unchecked
provenance flag must not be set just to force acceptance.
Supply **only** its `input_context` object to `convert`/`render`; passing labels/after fields is rejected.
Output files must be new; errors are explicit and return nonzero.

These CLI examples use private, user-provided files that must not be committed.
No fetcher, hidden-state loader or training exporter is included.
The input/output schema is local, not the team's confirmed training-loader schema.

## Complete offline batch package

Provide the already accepted source/canonical files and the **existing** all/provisional
selected/excluded files, rather than recomputing dataset qualification or membership.
These are explicit input paths, not imports from old revision directories.

```powershell
python -B -m nes_converter batch --context-mode auto `
  --canonical .\private-inputs\canonical.jsonl `
  --accepted .\private-inputs\accepted.jsonl `
  --all-selected .\private-inputs\all-selected.jsonl `
  --all-excluded .\private-inputs\all-excluded.jsonl `
  --provisional-selected .\private-inputs\provisional-selected.jsonl `
  --provisional-excluded .\private-inputs\provisional-excluded.jsonl `
  --output .\offline-output
```

Outputs for **each view** include separate train/validation inputs, labels and expected-after
streams, plus byte-preserved membership files. Selection reason, evidence and contract
version are in `AUDIT.jsonl`, separate from the model messages. Input record metadata includes
the selected context mode and representation contract; none is injected into model messages.

The same member is emitted once per selected view; representation changes never append
new IDs. Both original empty no-edit labels are retained. Both views intentionally
overlap; do not combine them as disjoint datasets.

The historical complete delivery has all **2,503 train + 121 validation** and provisional
**2,449 train + 121 validation**, previously 2,580 structured and 44 raw inputs.
This repair independently verified all 2,624 source records, but **no complete new
package was generated**: 239 train records contain the raw wrapper's reserved outer
tags as code literals and are explicitly blocked. Bounded diagnostics rendered
2,385 records (2,264 train + 121 validation), all raw; these are not a partial
successful release. The 44 old raw messages remain equal; 2,341 others change only
the related-context representation. No record was removed from either policy.

The local input-record schema is `local-source-faithful-nes-candidates-v2`; selection
contract is `nes-source-faithful-context-v2`. Audit fields are separate:

- `baseline_cache_consistency`: accepted/canonical input, patch and after equality.
- `source_input_fidelity`: original normalized message spans match all canonical inputs.
- `source_target_linkage`: original assistant region rewrite equals expected after;
  the patch reaches that independently extracted after.
- `renderer_target_isolation`: changing the original assistant and rerunning the
  independent span extractor plus renderer leaves messages unchanged. The native
  source-adapter-to-renderer path is separately tested on synthetic alternatives,
  not claimed as rerun for every real record.
- `patch_replay`: shared original-snapshot patch mechanics reach the verified after.

The independent checker does not call the native adapter, snippet splitter or renderer.
It uses exact unique source sections and declared region/cursor markers, with only
CRLF-to-LF normalization. It does not independently prove original IDE provenance or
the lexical origin of those published markers. Patch application is a shared helper.
These checks do not certify semantic correctness or absence of all data leakage.

All checks must pass. Errors return nonzero and leave no success summary/manifest; a partially written
directory is not a successful package. Use a fresh output path after investigating failure.
Output lengths are recorded; nothing is silently truncated to meet an unverified token budget.

## Representation boundaries

Current code and output coordinates remain excerpt-local; historical coordinates remain
their published past-source domains with no inferred offsets. System/output instructions
are unchanged. In v019, the complete context body after the exact source-task prefix is
retained, including literal markers. Existing CRLF-to-LF normalization belongs to the native
adapter, not a new renderer transformation. Only the leading fixed task prefix is
removed; repetitions in the body remain. Wrapper collisions fail explicitly even when
the conflicting tags are source-code literals. No escaping, deletion, alternate
framing, or legacy structured fallback is applied.

Original grouping, token IDs/chat-template interpretation, token budgets, model behavior
and production/training readiness are **not** verified by a successful conversion.

## Source inclusion and disclosure

[Handoff and provenance](docs/HANDOFF.md), [file inventory](INVENTORY.json) and
[third-party notices](THIRD_PARTY_NOTICES.md) describe the curated source boundary.
Only synthetic code bodies and the fixed public Instinct system instruction are test fixtures.
No original/bulk data, full real prompts, personal captures, credentials, environments,
caches, model assets or large logs are included.

`.gitignore` is a source allowlist, not a secret scanner. It cannot undo already tracked
content or protect against `git add -f`. Review the actual proposed file inventory and
staged diff before any future commit/push. No project-wide outbound license or repository
visibility decision is made here; team ownership and applicable rights remain an approval gate.
