"""Streaming complete offline views from existing accepted records and explicit policies."""
import copy
import hashlib
import json
import shutil
from collections import Counter
from contextlib import ExitStack
from itertools import zip_longest
from pathlib import Path

from .instinct import REVISION
from .patch import apply_patch
from .runtime import require
from .selection import CONTRACT, select_and_render
from .source_fidelity import alternate_target_input, equal, verify_original


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def read_rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in {Path(path).name}, line {number}: {error.msg}") from error


def load_policy(selected_path, excluded_path):
    result = {}
    for decision, path in (("selected", selected_path), ("excluded", excluded_path)):
        entries = {}
        for number, record in read_rows(path):
            sid = record["sample_id"]
            require(sid not in entries, f"Duplicate {decision} membership at line {number}: {sid}")
            require(record["decision"] == decision, f"Wrong membership decision: {sid}")
            entries[sid] = record
        result[decision] = entries
    require(not result["selected"].keys() & result["excluded"].keys(), "Selected/excluded membership overlaps")
    return result


def check_source(canonical, accepted):
    sid = canonical["id"]
    source = accepted["source_before"]
    require(accepted["status"] == "accepted", f"Record was not accepted: {sid}")
    require(source["sample_id"] == sid == accepted["case_id"], f"Source/canonical IDs disagree: {sid}")
    require(source["dataset"] == "continuedev/instinct-data" and source["revision"] == REVISION
            and source["viewer_revision_verified"] is True, f"Source provenance differs: {sid}")
    equal(sid, "cache.input_context", accepted["input_context"], canonical["input_context"])
    equal(sid, "cache.patch", accepted["converted_patch"], canonical["patch"])
    equal(sid, "cache.expected_result", accepted["expected_result"], canonical["expected_result"])
    require(source["split"] in ("train_typescript", "test_typescript"), f"Unrecognized source split: {sid}")
    verify_original(canonical, source)
    return source["split"], "validation-only" if source["split"] == "test_typescript" else "train-candidate"


def run_batch(*, canonical_path, accepted_path, policies, output, context_mode):
    output = Path(output)
    require(not output.exists(), "Output already exists; use an unused output directory")
    require(set(policies) == {"all", "provisional"}, "Require explicit all and provisional policy files")
    loaded = {name: load_policy(*paths) for name, paths in policies.items()}
    source_inventory = {
        "canonical": {"name": Path(canonical_path).name, "sha256": file_hash(canonical_path)},
        "accepted": {"name": Path(accepted_path).name, "sha256": file_hash(accepted_path)},
        "policies": {
            name: {key: {"name": Path(path).name, "sha256": file_hash(path)}
                   for key, path in zip(("selected", "excluded"), paths)}
            for name, paths in policies.items()
        },
    }
    output.mkdir(parents=True)
    seen = set()
    counts = Counter()
    view_counts = {name: Counter() for name in policies}
    no_edits = []
    with ExitStack() as stack:
        streams = {}
        for name, paths in policies.items():
            directory = output / name
            directory.mkdir()
            for key, path in zip(("selected", "excluded"), paths):
                shutil.copyfile(path, directory / f"baseline-{key}.jsonl")
            streams[name] = {
                f"{split}-{kind}": stack.enter_context(
                    (directory / f"{split}-{kind}.jsonl").open("x", encoding="utf-8", newline="\n")
                ) for split in ("train", "validation") for kind in ("inputs", "labels", "expected-after")
            }
        audit_stream = stack.enter_context((output / "AUDIT.jsonl").open("x", encoding="utf-8", newline="\n"))
        source_streams = zip_longest(read_rows(canonical_path), read_rows(accepted_path))
        for canonical_item, accepted_item in source_streams:
            require(canonical_item is not None and accepted_item is not None, "Source file row counts differ")
            line_number, record = canonical_item
            accepted_line, accepted = accepted_item
            require(line_number == accepted_line, "Source streams lost alignment")
            sid = record["id"]
            require(sid not in seen, f"Duplicate canonical ID: {sid}")
            seen.add(sid)
            split, role = check_source(record, accepted)
            before = copy.deepcopy(record["input_context"])
            try:
                result = select_and_render(record["input_context"], context_mode=context_mode)
            except ValueError as error:
                raise ValueError(f"Renderer failure for {sid}: {error}") from error
            require(before == record["input_context"], f"Renderer mutated input: {sid}")
            alternate = alternate_target_input(accepted["source_before"])
            require(result == select_and_render(alternate, context_mode=context_mode),
                    f"Target-sensitive rendering: {sid}")
            require(apply_patch(before["files"], record["patch"]) == record["expected_result"],
                    f"Original patch replay mismatch: {sid}")
            selection = result["selection"]
            counts[selection["context_mode"]] += 1
            emitted_views = []
            input_row = {
                "sample_id": sid, "split": split, "evaluation_role": role,
                "schema": "local-source-faithful-nes-candidates-v2", "status": "OFFLINE_NES_CANDIDATE",
                "context_mode": selection["context_mode"], "mapping_contract": selection["representation_contract"],
                "messages": result["messages"],
            }
            for name, policy in loaded.items():
                require(sid in policy["selected"] or sid in policy["excluded"],
                        f"Policy {name} does not classify existing source ID: {sid}")
                if sid not in policy["selected"]:
                    continue
                member = policy["selected"][sid]
                require(member["split"] == split and member["evaluation_role"] == role,
                        f"Policy role or split differs: {sid}")
                require(member["dataset"] == accepted["dataset"] and member["revision"] == REVISION,
                        f"Policy source identity differs: {sid}")
                category = "validation" if role == "validation-only" else "train"
                for kind, value in (
                    ("inputs", input_row),
                    ("labels", {"sample_id": sid, "assistant_label": {"role": "assistant", "content": record["patch"]}}),
                    ("expected-after", {"sample_id": sid, "expected_result": record["expected_result"]}),
                ):
                    streams[name][f"{category}-{kind}"].write(
                        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                view_counts[name][category] += 1
                view_counts[name][selection["context_mode"]] += 1
                emitted_views.append(name)
            if record["patch"] == "":
                no_edits.append({"sample_id": sid, "role": role, "views": emitted_views,
                                 "empty_label_preserved": True})
            audit = {
                "sample_id": sid, "canonical_line_one_based": line_number, "accepted_line_one_based": accepted_line,
                "split": split, "evaluation_role": role, "views": emitted_views, "selection": selection,
                "source_input_sha256": object_hash(before), "messages_sha256": object_hash(result["messages"]),
                "label_sha256": object_hash(record["patch"]), "expected_after_sha256": object_hash(record["expected_result"]),
                "baseline_cache_consistency": {"passed": True, "scope": "Accepted/canonical input, patch and after equality"},
                "source_input_fidelity": {"passed": True, "scope": "Independent normalized message spans, all input fields"},
                "source_target_linkage": {"passed": True, "scope": "Original assistant region rewrite and patch reach source-derived after"},
                "renderer_target_isolation": {
                    "passed": True,
                    "scope": "Change original assistant only; independent source extractor -> renderer yields identical messages",
                    "native_adapter_end_to_end": "Covered separately by synthetic tests, not claimed for this per-record check"},
                "patch_replay": {"passed": True, "scope": "Original-snapshot patch mechanics against independently linked expected after"},
                "input_characters": {message["role"]: len(message["content"]) for message in result["messages"]},
                "token_budget_verified": False, "truncated": False,
            }
            audit_stream.write(json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n")
    for name, policy in loaded.items():
        require(set(policy["selected"]) | set(policy["excluded"]) == seen, f"Policy {name} has unmatched source IDs")
    require(file_hash(canonical_path) == source_inventory["canonical"]["sha256"]
            and file_hash(accepted_path) == source_inventory["accepted"]["sha256"], "Source changed during conversion")
    for name, paths in policies.items():
        for key, path in zip(("selected", "excluded"), paths):
            require(file_hash(path) == source_inventory["policies"][name][key]["sha256"],
                    "Membership policy changed during conversion")
    summary = {
        "status": "OFFLINE_CANDIDATE_CONVERSION_COMPLETE", "converter_contract": CONTRACT,
        "requested_context_mode": context_mode, "unique_source_records": len(seen),
        "context_counts": dict(counts), "views": {name: dict(count) for name, count in view_counts.items()},
        "no_edit_records": no_edits, "source_inventory": source_inventory,
        "failures": 0, "skips": 0, "original_grouping_recovered": False,
        "production_contract_approved": False, "training_ready": False, "model_or_tokenizer_loaded": False,
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    inventory = {
        file.relative_to(output).as_posix(): {"bytes": file.stat().st_size, "sha256": file_hash(file)}
        for file in sorted(output.rglob("*")) if file.is_file()
    }
    (output / "MANIFEST.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return summary
