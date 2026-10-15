"""Synthetic source-only packaging tests; no published sample payloads."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nes_converter.api import render_input
from nes_converter.errors import MappingSkip, Rejection
from nes_converter.instinct import REVISION, adapt
from nes_converter.patch import apply_patch, make_patch
from nes_converter.prompt import guard, history, text, v017, v019
from nes_converter.runtime import run_node


def context(body=None):
    return {
        "files": {"demo.ts": "let count = 1;"},
        "cursor": {"line_zero_based": 0, "column_codepoints_zero_based": 14, "column_utf16_units_zero_based": 14},
        "instruction": None, "recent_history": "",
        "related_context": text.SOURCE_PREFIX + (
            "<|context_file|> helpers.ts\n<|snippet|>\nexport const scale = 2;" if body is None else body
        ),
    }


def collision_body():
    return (
        "<|context_file|> unit.test.ts\n<|snippet|>\n"
        "const example = `alpha\n<|context_file|> embedded-name\n<|snippet|>\nomega`;"
    )


def native_record(code="old();<|user_cursor_is_here|>", target="new();", split="train_typescript"):
    system = (Path(__file__).parent / "fixtures" / "instinct-system.txt").read_text(encoding="utf-8")
    return {
        "dataset": "continuedev/instinct-data", "revision": REVISION,
        "viewer_revision_verified": True, "sample_id": "synthetic-handoff", "split": split,
        "row": {"messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": (
                text.SOURCE_PREFIX + "### User Edits:\n\n### User Excerpt:\n\"demo.ts\"\n\n"
                "<|editable_region_start|>\n" + code + "\n<|editable_region_end|>"
            )},
            {"role": "assistant", "content": target},
        ]},
    }


class HandoffTests(unittest.TestCase):
    def test_v017_complete_synthetic_message(self):
        result = render_input(context(), mode="v017-structured")
        expected = (
            v017.PREFIX
            + "<|recently_viewed_code_snippets|>\n<|recently_viewed_code_snippet|>\n"
            "code_snippet_file_path: helpers.ts\nexport const scale = 2;\n"
            "<|/recently_viewed_code_snippet|>\n<|/recently_viewed_code_snippets|>\n\n"
            "<|current_file_content|>\ncurrent_file_path: demo.ts\n0|let count = 1;\n"
            "<|/current_file_content|>\n\n<|edit_diff_history|>\n\n<|/edit_diff_history|>\n\n"
            "<|cursor_location|>\n0|let count = 1;<|cursor|>\n<|/cursor_location|>"
            + v017.TEMPLATE["postscript"]
        )
        self.assertEqual(result["messages"], [
            {"role": "system", "content": v017.TEMPLATE["system"]},
            {"role": "user", "content": expected},
        ])

    def test_no_default_mode_or_silent_promotion(self):
        with self.assertRaises(TypeError):
            render_input(context())
        with self.assertRaises(ValueError):
            render_input(context(), mode="automatic")

    def test_distinct_collision_modes_and_full_literal(self):
        source = context(collision_body())
        old = render_input(source, mode="v017-structured")
        self.assertIn("code_snippet_file_path: embedded-name", old["messages"][1]["content"])
        with self.assertRaises(guard.ContextFidelityError):
            render_input(source, mode="v018-guarded")
        new = render_input(source, mode="v019-independent")
        body = new["messages"][1]["content"].split(v019.BEGIN + "\n")[1].split("\n" + v019.END)[0]
        self.assertEqual(body, collision_body())
        self.assertEqual(new["generated_file_associations"], [])
        self.assertFalse(new["original_grouping_recovered"])
        self.assertEqual(old["messages"][0], new["messages"][0])
        closing = "<|/recently_viewed_code_snippets|>"
        self.assertEqual(old["messages"][1]["content"].split(closing)[1],
                         new["messages"][1]["content"].split(closing)[1])

    def test_noncollision_v019_does_not_switch_representation(self):
        old = render_input(context(), mode="v017-structured")
        for mode in ("v018-guarded", "v019-independent"):
            current = render_input(context(), mode=mode)
            self.assertEqual(current["representation"], old["representation"])
            self.assertEqual(current["messages"], old["messages"])

    def test_targets_not_available_to_renderer(self):
        source = context(collision_body())
        original = copy.deepcopy(source)
        record = {"input_context": source, "expected_result": "target one", "patch": "label one"}
        first = render_input(record["input_context"], mode="v019-independent")
        record.update(expected_result="different target", patch="different label")
        self.assertEqual(first, render_input(record["input_context"], mode="v019-independent"))
        record.pop("expected_result")
        record.pop("patch")
        self.assertEqual(first, render_input(record["input_context"], mode="v019-independent"))
        self.assertEqual(source, original)
        with self.assertRaises(MappingSkip):
            render_input({**source, "expected_result": {}}, mode="v019-independent")

    def test_unicode_cursor_uses_both_coordinate_conventions(self):
        source = context()
        source["files"] = {"demo.ts": 'const face = "\U0001f600";'}
        line = source["files"]["demo.ts"]
        source["cursor"] = {
            "line_zero_based": 0, "column_codepoints_zero_based": len(line),
            "column_utf16_units_zero_based": len(line.encode("utf-16-le")) // 2,
        }
        self.assertIn(line + "<|cursor|>", render_input(source, mode="v017-structured")["messages"][1]["content"])
        source["cursor"]["column_utf16_units_zero_based"] -= 1
        with self.assertRaises(ValueError):
            render_input(source, mode="v017-structured")

    def test_history_keeps_past_coordinates_outside_excerpt(self):
        source = context()
        source["recent_history"] = 'User edited file "demo.ts"\n\n```diff\n@@ -91 +91 @@\n-old();\n+new();\n```'
        user = render_input(source, mode="v017-structured")["messages"][1]["content"]
        self.assertIn("@@ -90,1 +90,1 @@\n-old();\n+new();", user)
        self.assertIn("current_file_path: demo.ts\n0|let count = 1;", user)

    def test_aggregate_first_header_grammar_is_preserved(self):
        parsed = history.parse_diff("@@ -1,3 +1,3 @@\n-a\n+b\n@@ -4 +4 @@\n-c\n+d")
        self.assertEqual(parsed["grammar"], "producer-aggregate-first-header")
        self.assertEqual([h["startLineNumber"] for h in parsed["hunks"]], [0, 3])
        with self.assertRaises(history.HistoryAmbiguity):
            history.parse_diff("@@ -1,99 +1,99 @@\n-a\n+b")

    def test_header_only_reference_and_code_marker_not_deleted(self):
        source = context('<|context_file|> Untitled.txt\n<|context_file|> a.ts\n<|snippet|>\n'
                         'const text = "<|context_file|> <|snippet|>";')
        user = render_input(source, mode="v017-structured")["messages"][1]["content"]
        self.assertIn("code_snippet_file_path: Untitled.txt\n\n", user)
        self.assertIn('const text = "<|context_file|> <|snippet|>";', user)

    def test_raw_wrapper_collisions_fail(self):
        for marker in (v019.BEGIN, v019.END, "<|recently_viewed_code_snippets|>",
                       "<|/recently_viewed_code_snippets|>"):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "wrapper collision"):
                v019.render_raw_context(context(collision_body() + "\n" + marker))

    def test_noop_and_multiple_original_snapshot_edits(self):
        before = {"a.ts": "a\nb\nc\nd"}
        after = {"a.ts": "A\nb\nC\nd"}
        delta = make_patch(before, after)
        self.assertEqual(apply_patch(before, delta), after)
        self.assertEqual(make_patch(before, before), "")
        self.assertEqual(apply_patch(before, ""), before)

    def test_native_adapter_end_to_end_and_validation_role(self):
        record = native_record(split="test_typescript")
        original = copy.deepcopy(record)
        canonical = adapt(record)
        self.assertEqual(canonical.input_context["files"], {"demo.ts": "old();"})
        self.assertEqual(canonical.expected_result, {"demo.ts": "new();"})
        self.assertEqual(canonical.metadata["evaluation_role"], "validation-only")
        delta = make_patch(canonical.input_context["files"], canonical.expected_result)
        self.assertEqual(apply_patch(canonical.input_context["files"], delta), canonical.expected_result)
        self.assertEqual(record, original)
        self.assertEqual(len(render_input(canonical.input_context, mode="v018-guarded")["messages"]), 2)

    def test_native_system_revision_and_literal_cursor_guards_unchanged(self):
        for change in ({"revision": "unverified"}, {"viewer_revision_verified": False}):
            source = native_record()
            source.update(change)
            with self.assertRaises(Rejection):
                adapt(source)
        with self.assertRaises(Rejection):
            adapt(native_record('const text = "<|user_cursor_is_here|>";'))

    def test_native_existing_crlf_policy(self):
        source = native_record(target="new();\r\n")
        canonical = adapt(source)
        self.assertTrue(canonical.metadata["source_adapter"]["eol"]["normalization_performed"])
        self.assertEqual(canonical.expected_result, {"demo.ts": "new();\n"})

    def test_missing_node_is_explicit_not_a_fallback(self):
        with patch("nes_converter.runtime.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not on PATH"):
                run_node(Path("unused.cjs"), {})

    def test_cli_requires_mode_writes_input_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "input.json", root / "output.json"
            source.write_text(json.dumps(context()), encoding="utf-8")
            command = [sys.executable, "-B", "-m", "nes_converter", "render",
                       "--input", str(source), "--output", str(target)]
            missing = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertFalse(target.exists())
            command += ["--mode", "v018-guarded"]
            success = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["messages"],
                             render_input(context(), mode="v018-guarded")["messages"])
            existing = target.read_bytes()
            failure = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failure.returncode, 2)
            self.assertEqual(target.read_bytes(), existing)

    def test_cli_adapt_source_separates_target_from_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            target = Path(directory) / "canonical.json"
            source.write_text(json.dumps(native_record()), encoding="utf-8")
            process = subprocess.run([sys.executable, "-B", "-m", "nes_converter", "adapt",
                                      "--input", str(source), "--output", str(target)],
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result["assistant_label"], {"role": "assistant", "content": "demo.ts:0\n-old();\n+new();"})
            self.assertEqual(result["expected_result"], {"demo.ts": "new();"})
            self.assertNotIn("messages", result)


if __name__ == "__main__":
    unittest.main()
