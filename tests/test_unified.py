"""Synthetic integration tests for the new content-selected full-package CLI."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nes_converter.batch import run_batch
from nes_converter.instinct import REVISION
from nes_converter.prompt import guard, text, v017, v019
from nes_converter.selection import select_and_render
from test_handoff import collision_body, context


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def batch_fixture(root):
    canonical = []
    accepted = []
    selected = []
    for index, body in enumerate((None, collision_body(), None)):
        sid = f"synthetic:{index}"
        source = context(body)
        split = "test_typescript" if index == 2 else "train_typescript"
        role = "validation-only" if index == 2 else "train-candidate"
        row = {"id": sid, "input_context": source, "patch": "",
               "expected_result": copy.deepcopy(source["files"])}
        canonical.append(row)
        accepted.append({
            "case_id": sid, "status": "accepted", "dataset": "continuedev/instinct-data",
            "input_context": copy.deepcopy(source), "converted_patch": "", "expected_result": row["expected_result"],
            "source_before": {
                "sample_id": sid, "dataset": "continuedev/instinct-data", "revision": REVISION,
                "viewer_revision_verified": True, "split": split,
                "row": {"messages": [
                    {"role": "system", "content": (Path(__file__).parent / "fixtures" / "instinct-system.txt").read_text()},
                    {"role": "user", "content": source["related_context"] + '### User Edits:\n### User Excerpt:\n"demo.ts"\n\n'
                     + '<|editable_region_start|>\nlet count = 1;<|user_cursor_is_here|>\n<|editable_region_end|>'},
                    {"role": "assistant", "content": "let count = 1;"},
                ]},
            },
        })
        selected.append({
            "sample_id": sid, "decision": "selected", "dataset": "continuedev/instinct-data",
            "revision": REVISION, "split": split, "evaluation_role": role,
        })
    paths = {name: root / f"{name}.jsonl" for name in (
        "canonical", "accepted", "all-selected", "all-excluded", "provisional-selected", "provisional-excluded"
    )}
    for name, rows in (
        ("canonical", canonical), ("accepted", accepted), ("all-selected", selected), ("all-excluded", []),
        ("provisional-selected", selected[1:]),
        ("provisional-excluded", [{**selected[0], "decision": "excluded"}]),
    ):
        write_rows(paths[name], rows)
    return paths


class UnifiedTests(unittest.TestCase):
    def test_auto_selection_has_no_identity_argument_or_target_dependency(self):
        source = context(collision_body())
        changed_names = copy.deepcopy(source)
        changed_names["files"] = {"different-current-name.ts": next(iter(source["files"].values()))}
        changed_names["related_context"] = changed_names["related_context"].replace(
            "unit.test.ts", "not-a-path").replace("embedded-name", "arbitrary words")
        for item in (source, changed_names):
            result = select_and_render(item, context_mode="auto")
            self.assertEqual(result["selection"]["context_mode"], "raw")
            self.assertEqual(result["selection"]["reason"], "NONEMPTY_CONTEXT_WITHOUT_TRUSTED_BOUNDARIES")
            for field in ("sample_id", "expected_result", "patch"):
                with self.assertRaises(v017.MappingSkip):
                    select_and_render({**item, field: "unused"}, context_mode="auto")

    def test_auto_does_not_call_unsafe_splitter_on_collision(self):
        with patch("nes_converter.prompt.v017.map_snippets", side_effect=AssertionError("Unsafe splitter called")):
            result = select_and_render(context(collision_body()), context_mode="auto")
        self.assertEqual(result["selection"]["context_mode"], "raw")

    def test_closed_literal_and_true_header_counterexamples(self):
        self.assertEqual(select_and_render(context(), context_mode="auto")["selection"]["context_mode"], "raw")
        body = ("<|context_file|> a.ts\n<|snippet|>\nconst a = 1;\n"
                "<|context_file|> b.ts\n<|snippet|>\nconst b = 2;")
        self.assertEqual(select_and_render(context(body), context_mode="auto")["selection"]["context_mode"], "raw")
        truncated = ("<|context_file|> a.ts\n<|snippet|>\nconst a = `open\n"
                     "<|context_file|> b.ts\n<|snippet|>\nconst b = 2;")
        self.assertEqual(select_and_render(context(truncated), context_mode="auto")["selection"]["context_mode"], "raw")

    def test_explicit_modes_keep_their_requested_semantics(self):
        raw = select_and_render(context(), context_mode="raw")
        self.assertEqual(raw["selection"]["reason"], "EXPLICIT_RAW_CONTEXT")
        self.assertIn(v019.BEGIN, raw["messages"][1]["content"])
        empty = context()
        empty["related_context"] = text.SOURCE_PREFIX
        structured = select_and_render(empty, context_mode="structured")
        self.assertEqual(structured["selection"]["reason"], "EMPTY_CONTEXT_NO_GROUPING_REQUIRED")
        with self.assertRaises(v017.MappingSkip):
            select_and_render(context(collision_body()), context_mode="structured")

    def test_unknown_context_and_wrapper_collisions_are_not_swallowed(self):
        source = context(collision_body() + "\n" + v019.END)
        with self.assertRaisesRegex(ValueError, "wrapper collision"):
            select_and_render(source, context_mode="auto")
        with self.assertRaises(ValueError):
            select_and_render(context(), context_mode="unknown")
        source = context()
        source["related_context"] = "unrecognized framing"
        with self.assertRaises(v017.MappingSkip):
            select_and_render(source, context_mode="auto")

    def test_complete_batch_replaces_members_without_appending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = batch_fixture(root)
            policies = {name: (paths[f"{name}-selected"], paths[f"{name}-excluded"])
                        for name in ("all", "provisional")}
            summary = run_batch(
                canonical_path=paths["canonical"], accepted_path=paths["accepted"],
                policies=policies, output=root / "out", context_mode="auto",
            )
            self.assertEqual(summary["unique_source_records"], 3)
            self.assertEqual(summary["context_counts"], {"raw": 3})
            self.assertEqual(summary["views"]["all"], {"train": 2, "raw": 3, "validation": 1})
            self.assertEqual(summary["views"]["provisional"]["train"], 1)
            self.assertEqual(len(summary["no_edit_records"]), 3)
            audit = [json.loads(line) for line in (root / "out" / "AUDIT.jsonl").read_text().splitlines()]
            self.assertEqual(len({row["sample_id"] for row in audit}), 3)
            for view in ("all", "provisional"):
                inputs = [json.loads(line) for line in (root / "out" / view / "train-inputs.jsonl").read_text().splitlines()]
                self.assertTrue(all("selection" not in row for row in inputs))
                labels = [json.loads(line) for line in (root / "out" / view / "train-labels.jsonl").read_text().splitlines()]
                self.assertTrue(all(row["assistant_label"]["content"] == "" for row in labels))
                persisted = (root / "out" / view / "train-labels.jsonl").read_text()
                self.assertEqual(persisted, "".join(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for row in labels))

    def test_cli_partial_failure_is_nonzero_with_no_success_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = batch_fixture(root)
            records = [json.loads(line) for line in paths["accepted"].read_text().splitlines()]
            records[1]["converted_patch"] = "incorrect"
            write_rows(paths["accepted"], records)
            output = root / "output"
            command = [sys.executable, "-B", "-m", "nes_converter", "batch", "--context-mode", "auto",
                       "--output", str(output)]
            for name, path in paths.items():
                command.extend(["--" + name, str(path)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cache.patch", result.stderr)
            self.assertIn("synthetic:1", result.stderr)
            self.assertFalse((output / "SUMMARY.json").exists())
            self.assertFalse((output / "MANIFEST.json").exists())

    def test_changed_membership_and_duplicate_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = batch_fixture(root)
            selected = [json.loads(line) for line in paths["all-selected"].read_text().splitlines()]
            selected[1]["evaluation_role"] = "validation-only"
            write_rows(paths["all-selected"], selected)
            with self.assertRaisesRegex(ValueError, "Policy role or split differs"):
                run_batch(canonical_path=paths["canonical"], accepted_path=paths["accepted"],
                          policies={name: (paths[f"{name}-selected"], paths[f"{name}-excluded"])
                                    for name in ("all", "provisional")},
                          output=root / "out", context_mode="auto")


if __name__ == "__main__":
    unittest.main()
