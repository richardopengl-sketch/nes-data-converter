import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nes_converter.batch import check_source, run_batch
from nes_converter.instinct import adapt
from nes_converter.prompt import text, v017, v019
from nes_converter.selection import select_and_render
from nes_converter.source_fidelity import SourceFidelityError, extract_published
from test_handoff import context, native_record
from test_unified import batch_fixture, write_rows

CASES = [
    "const example: string = `alpha\n<|context_file|> phantom.ts\n<|snippet|>\nomega`;",
    "const example = `alpha ${name}\n<|context_file|> phantom.ts\n<|snippet|>\nomega`;",
    "function example() {\nreturn `alpha\n<|context_file|> phantom.ts\n<|snippet|>\nomega`;\n}",
    # Different known source groupings, neither reconstructible from the flat published representation alone.
    "<|context_file|> first.ts\n<|snippet|>\nconst a = 1;\n<|context_file|> second.ts\n<|snippet|>\nconst b = 2;",
    "const nested = `<|context_file|> first.ts\n<|snippet|>\na\n<|context_file|> second.ts\n<|snippet|>\nb`;",
    "return `unfinished\n<|context_file|> phantom.ts\n<|snippet|>\n",
    "\n \t\n// \u4e2d\U0001f600\n\n" + text.SOURCE_PREFIX + "\n \t",
]


class SourceFidelityTests(unittest.TestCase):
    def test_all_manual_bodies_preserved_without_classifying_or_splitting(self):
        for body in CASES:
            with self.subTest(body=body[:35]):
                published = body if body.startswith("<|context_file|>") else "<|context_file|> real.ts\n<|snippet|>\n" + body
                source = context(published)
                before = copy.deepcopy(source)
                legacy = v017.render_messages(v017.map_input(context()))
                for mode in ("auto", "raw"):
                    with patch("nes_converter.prompt.guard.ambiguous_boundaries", side_effect=AssertionError("classifier called")), \
                         patch("nes_converter.prompt.v017.map_snippets", side_effect=AssertionError("splitter called")):
                        result = select_and_render(source, context_mode=mode)
                    user = result["messages"][1]["content"]
                    raw = user.split(v019.BEGIN + "\n", 1)[1].split("\n" + v019.END, 1)[0]
                    self.assertEqual(raw, published)
                    self.assertNotIn("code_snippet_file_path:", user)
                    self.assertEqual(result["messages"][0], legacy[0])
                    self.assertEqual(user.split(v019.CLOSE, 1)[1], legacy[1]["content"].split(v019.CLOSE, 1)[1])
                    self.assertEqual(source, before)
                with self.assertRaisesRegex(v017.MappingSkip, "boundary contract"):
                    select_and_render(source, context_mode="structured")

    def test_whitespace_only_body_is_not_silently_removed(self):
        result = select_and_render(context(" \n\n\t"), context_mode="auto")
        self.assertEqual(result["selection"]["context_mode"], "raw")
        self.assertIn(v019.BEGIN + "\n \n\n\t\n" + v019.END, result["messages"][1]["content"])

    def test_wrapper_collision_fails_even_when_classifier_unavailable(self):
        for delimiter in (v019.BEGIN, v019.END, v019.OPEN.rstrip("\n"), v019.CLOSE.lstrip("\n")):
            with self.subTest(delimiter=delimiter):
                with patch("nes_converter.prompt.guard.ambiguous_boundaries", side_effect=AssertionError("called")):
                    with self.assertRaisesRegex(ValueError, "wrapper collision"):
                        select_and_render(context(delimiter), context_mode="raw")

    def test_independent_manual_unicode_spans_fields_and_rewrite(self):
        source = native_record()
        related = text.SOURCE_PREFIX + "<|context_file|> helper.ts\n<|snippet|>\nexport const scale = 2;\n\n"
        history = 'User edited file "old.ts"\n\n```diff\n@@ -5 +5 @@\n-a\n+b\n```\n'
        source["row"]["messages"][1]["content"] = (
            related + "### User Edits:\n" + history + '### User Excerpt:\n"unicode.ts"\n\n'
            'head();\n<|editable_region_start|>\nconst x = "\U0001f600";<|user_cursor_is_here|>\n\n'
            '<|editable_region_end|>\ntail();\n'
        ).replace("\n", "\r\n")
        source["row"]["messages"][2]["content"] = "changed();\r\n"
        result = extract_published(source)
        self.assertEqual(result["input_context"], {
            "files": {"unicode.ts": 'head();\nconst x = "\U0001f600";\n\ntail();\n'},
            "cursor": {"line_zero_based": 1, "column_codepoints_zero_based": 14, "column_utf16_units_zero_based": 15},
            "instruction": None, "related_context": related, "recent_history": history,
        })
        self.assertEqual(result["expected_result"], {"unicode.ts": "head();\nchanged();\n\ntail();\n"})

    def test_full_batch_wrapper_collision_identifies_record_and_has_no_success_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = batch_fixture(root)
            canonical = [json.loads(line) for line in paths["canonical"].read_text().splitlines()]
            accepted = [json.loads(line) for line in paths["accepted"].read_text().splitlines()]
            related = text.SOURCE_PREFIX + '<|context_file|> tokens.ts\n<|snippet|>\nconst tag = "<|recently_viewed_code_snippets|>";'
            previous = canonical[1]["input_context"]["related_context"]
            canonical[1]["input_context"]["related_context"] = related
            accepted[1]["input_context"]["related_context"] = related
            user = accepted[1]["source_before"]["row"]["messages"][1]
            self.assertTrue(user["content"].startswith(previous))
            user["content"] = related + user["content"][len(previous):]
            write_rows(paths["canonical"], canonical)
            write_rows(paths["accepted"], accepted)
            output = root / "output"
            command = [sys.executable, "-B", "-m", "nes_converter", "batch",
                       "--context-mode", "auto", "--output", str(output)]
            for name, path in paths.items():
                command.extend(["--" + name, str(path)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Renderer failure for synthetic:1", result.stderr)
            self.assertIn("Opaque wrapper collision", result.stderr)
            self.assertFalse((output / "SUMMARY.json").exists())
            self.assertFalse((output / "MANIFEST.json").exists())

    def test_shared_cache_errors_fail_complete_batch(self):
        mutators = {
            "truncated": lambda c: c.update(related_context=text.SOURCE_PREFIX),
            "middle_deleted": lambda c: c.update(related_context=c["related_context"].replace("export const scale = 2;", "")),
            "duplicated": lambda c: c.update(related_context=c["related_context"] + "export const scale = 2;"),
            "reordered": lambda c: c.update(related_context=c["related_context"].replace(
                "export const scale = 2;\nexport const next = 3;", "export const next = 3;\nexport const scale = 2;")),
            "code": lambda c: c.update(files={"demo.ts": "let WRONG = 1;"}),
            "path": lambda c: c.update(files={"wrong.ts": "let count = 1;"}),
            "cursor": lambda c: c["cursor"].update(column_codepoints_zero_based=0, column_utf16_units_zero_based=0),
            "history": lambda c: c.update(recent_history="invented history"),
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = batch_fixture(root)
                canonical = [json.loads(line) for line in paths["canonical"].read_text().splitlines()]
                accepted = [json.loads(line) for line in paths["accepted"].read_text().splitlines()]
                body = text.SOURCE_PREFIX + "<|context_file|> helper.ts\n<|snippet|>\nexport const scale = 2;\nexport const next = 3;"
                canonical[0]["input_context"]["related_context"] = body
                accepted[0]["source_before"]["row"]["messages"][1]["content"] = (
                    body + "### User Edits:\n" + accepted[0]["source_before"]["row"]["messages"][1]["content"].split("### User Edits:\n", 1)[1]
                )
                original_messages = copy.deepcopy(accepted[0]["source_before"])
                mutate(canonical[0]["input_context"])
                accepted[0]["input_context"] = copy.deepcopy(canonical[0]["input_context"])
                # Keep an empty, self-consistent patch, including after a current-code/path mutation.
                canonical[0]["expected_result"] = copy.deepcopy(canonical[0]["input_context"]["files"])
                accepted[0]["expected_result"] = copy.deepcopy(canonical[0]["expected_result"])
                write_rows(paths["canonical"], canonical)
                write_rows(paths["accepted"], accepted)
                with self.assertRaises(SourceFidelityError) as caught:
                    run_batch(canonical_path=paths["canonical"], accepted_path=paths["accepted"],
                              policies={view: (paths[f"{view}-selected"], paths[f"{view}-excluded"])
                                        for view in ("all", "provisional")}, output=root / "out", context_mode="auto")
                self.assertEqual(caught.exception.evidence["sample_id"], "synthetic:0")
                self.assertTrue(caught.exception.evidence["field"].startswith("input."))
                self.assertEqual(accepted[0]["source_before"], original_messages)
                self.assertFalse((root / "out" / "SUMMARY.json").exists())

    def test_shared_target_corruption_detected_despite_valid_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = batch_fixture(Path(folder))
            c = json.loads(paths["canonical"].read_text().splitlines()[0])
            a = json.loads(paths["accepted"].read_text().splitlines()[0])
            c["expected_result"] = a["expected_result"] = {"demo.ts": "changed();"}
            c["patch"] = a["converted_patch"] = "demo.ts:0\n-let count = 1;\n+changed();"
            with self.assertRaisesRegex(SourceFidelityError, "target.expected_after"):
                check_source(c, a)

    def test_nonunique_sections_are_not_guessed(self):
        for heading in ("### User Edits:\n", "### User Excerpt:\n"):
            source = native_record()
            source["row"]["messages"][1]["content"] = heading + source["row"]["messages"][1]["content"]
            with self.assertRaises(SourceFidelityError):
                extract_published(source)

    def test_native_adapter_to_renderer_answer_isolation(self):
        source = native_record()
        user = source["row"]["messages"][1]["content"]
        related = text.SOURCE_PREFIX + "<|context_file|> helper.ts\n<|snippet|>\nexport const scale = 2;\n"
        source["row"]["messages"][1]["content"] = related + user[len(text.SOURCE_PREFIX):]
        baseline = None
        expected_targets = []
        for target in ("old();", "differentValidTarget();", "// target-only-isolation-sentinel\nnew();"):
            modified = copy.deepcopy(source)
            modified["row"]["messages"][2]["content"] = target
            adapted = adapt(modified)
            rendered = select_and_render(adapted.input_context, context_mode="auto")["messages"]
            if baseline is None:
                baseline = rendered
            self.assertEqual(rendered, baseline)
            self.assertNotIn("target-only-isolation-sentinel", rendered[1]["content"])
            expected_targets.append(adapted.expected_result)
        self.assertNotEqual(expected_targets[0], expected_targets[1])


if __name__ == "__main__":
    unittest.main()
