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
    require(canonical["input_context"] == accepted["input_context"], f"Canonical input was changed: {sid}")
    require(canonical["patch"] == accepted["converted_patch"]
            and canonical["expected_result"] == accepted["expected_result"], f"Source-derived target changed: {sid}")
    require(source["split"] in ("train_typescript", "test_typescript"), f"Unrecognized source split: {sid}")
    user = [message["content"] for message in source["row"]["messages"] if message["role"] == "user"]
    require(len(user) == 1, f"Expected one original input message: {sid}")
    normalized = user[0].replace("\r\n", "\n")
    require(normalized.startswith(canonical["input_context"]["related_context"]),
            f"Related context is not from the original input prefix: {sid}")
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
            result = select_and_render(record["input_context"], context_mode=context_mode)
            require(before == record["input_context"], f"Renderer mutated input: {sid}")
            # Neither target-bearing record is passed to the selector.
            modified = {"input_context": copy.deepcopy(before), "patch": "different-target",
                        "expected_result": {"not_for_renderer": "different"}}
            removed = {"input_context": copy.deepcopy(before)}
            require(result == select_and_render(modified["input_context"], context_mode=context_mode)
                    == select_and_render(removed["input_context"], context_mode=context_mode),
                    f"Target-sensitive rendering: {sid}")
            require(apply_patch(before["files"], record["patch"]) == record["expected_result"],
                    f"Original patch replay mismatch: {sid}")
            selection = result["selection"]
            counts[selection["context_mode"]] += 1
            emitted_views = []
            input_row = {
                "sample_id": sid, "split": split, "evaluation_role": role,
                "schema": "local-unified-nes-candidates-v1", "status": "OFFLINE_NES_CANDIDATE",
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
                "source_linkage_passed": True, "target_isolation_passed": True, "patch_replay_passed": True,
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
