import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nes_converter.batch import object_hash, run_batch
from nes_converter.json_readback import verify_visible_messages
from nes_converter.prompt import v017, v019
from nes_converter.prompt.json_context import CONTRACT, NOTICE, encode_body
from nes_converter.selection import select_and_render
from test_handoff import context
from test_unified import batch_fixture

MANUAL_BODY = (
    r"literal newline escape: \n" + "\n"
    r"literal unicode escape: \u003c" + "\n"
    r"backslashes: C:\tmp\folder\\tail" + "\n"
    "actual Unicode: \u4e2d\U0001f600\nactual angles: <x>\n"
)
MANUAL_PAYLOAD = (
    r'{"schema":"nes-related-context-json-v1","text":"literal newline escape: \\n\n'
    r'literal unicode escape: \\u003c\nbackslashes: C:\\tmp\\folder\\\\tail\n'
    r'actual Unicode: \u4e2d\ud83d\ude00\nactual angles: \u003cx\u003e\n"}'
)


class JsonReadbackTests(unittest.TestCase):
    def test_jsonl_read_then_one_inner_decode_matches_handwritten_text(self):
        source = context(MANUAL_BODY)
        original = copy.deepcopy(source)
        messages = select_and_render(source, context_mode=CONTRACT)["messages"]
        prefix = v017.PREFIX + v019.OPEN + NOTICE + "\n"
        self.assertTrue(messages[1]["content"].startswith(prefix + MANUAL_PAYLOAD + v019.CLOSE))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text(json.dumps({"messages": messages}, ensure_ascii=False) + "\n", encoding="utf-8")
            transport = path.read_text(encoding="utf-8")
            loaded = json.loads(transport)["messages"]
        self.assertEqual(loaded, messages)
        self.assertIn(r"\\u003cx\\u003e", transport)
        self.assertIn(r"\u003cx\u003e", loaded[1]["content"])
        parse = json.JSONDecoder.raw_decode
        with patch("nes_converter.prompt.json_context.encode_body", side_effect=AssertionError("Encoder used by checker")), \
             patch("nes_converter.json_readback.json.JSONDecoder.raw_decode", autospec=True, side_effect=parse) as decoder:
            checked = verify_visible_messages(loaded, source, expected_messages_hash=object_hash(messages))
        self.assertEqual(decoder.call_count, 1)
        self.assertEqual(checked["decoded_body"], MANUAL_BODY)
        self.assertEqual(checked["payload"], MANUAL_PAYLOAD)
        self.assertEqual(source, original)

    def test_extra_serialization_and_decoding_damage_are_rejected(self):
        source = context(MANUAL_BODY)
        messages = select_and_render(source, context_mode=CONTRACT)["messages"]
        wrong_decoded = MANUAL_BODY.replace(r"\u003c", "<").replace(r"\n", "\n")
        self.assertNotEqual(wrong_decoded, MANUAL_BODY)
        for payload in (encode_body(MANUAL_PAYLOAD), encode_body(wrong_decoded), json.dumps(MANUAL_PAYLOAD)):
            with self.subTest(payload=payload):
                damaged = copy.deepcopy(messages)
                damaged[1]["content"] = damaged[1]["content"].replace(MANUAL_PAYLOAD, payload, 1)
                with self.assertRaises(ValueError):
                    verify_visible_messages(damaged, source, expected_messages_hash=object_hash(damaged))
        damaged = copy.deepcopy(messages)
        damaged[1]["content"] = json.dumps(damaged[1]["content"])
        with self.assertRaisesRegex(ValueError, "prefix"):
            verify_visible_messages(damaged, source, expected_messages_hash=object_hash(damaged))

    def test_transport_message_mutation_is_separate_from_body_check(self):
        source = context(MANUAL_BODY)
        messages = select_and_render(source, context_mode=CONTRACT)["messages"]
        changed = copy.deepcopy(messages)
        changed[1]["content"] += " "
        with self.assertRaisesRegex(ValueError, "pre-export"):
            verify_visible_messages(changed, source, expected_messages_hash=object_hash(messages))
        with self.assertRaisesRegex(ValueError, "boundary"):
            verify_visible_messages(changed, source, expected_messages_hash=object_hash(changed))

    def test_all_wrapper_literals_remain_data_without_changing_existing_modes(self):
        body = "\n".join((v019.OPEN.strip(), v019.CLOSE.strip(), v019.BEGIN, v019.END))
        source = context(body)
        with self.assertRaisesRegex(ValueError, "wrapper collision"):
            select_and_render(source, context_mode="auto")
        with self.assertRaises(ValueError):
            select_and_render(source, context_mode="structured")
        with patch("nes_converter.prompt.guard.ambiguous_boundaries", side_effect=AssertionError("Classifier used")), \
             patch("nes_converter.prompt.v017.map_snippets", side_effect=AssertionError("Splitter used")):
            messages = select_and_render(source, context_mode=CONTRACT)["messages"]
        checked = verify_visible_messages(messages, source, expected_messages_hash=object_hash(messages))
        self.assertEqual(checked["decoded_body"], body)
        self.assertNotIn(v019.OPEN.strip(), checked["payload"])
        self.assertNotIn(v019.CLOSE.strip(), checked["payload"])
        self.assertEqual(checked["payload"].count(v019.BEGIN), 1)
        self.assertEqual(checked["payload"].count(v019.END), 1)

    def test_complete_batch_readback_preserves_roles_members_and_empty_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = batch_fixture(root)
            summary = run_batch(
                canonical_path=paths["canonical"], accepted_path=paths["accepted"],
                policies={name: (paths[name + "-selected"], paths[name + "-excluded"])
                          for name in ("all", "provisional")},
                output=root / "out", context_mode=CONTRACT,
            )
            self.assertEqual(summary["status"], "EXPERIMENTAL_CONVERSION_COMPLETE_READBACK_PENDING")
            self.assertFalse(summary["readback_verified"])
            self.assertEqual(summary["unique_source_records"], 3)
            self.assertEqual(summary["views"]["all"]["train"], 2)
            self.assertEqual(summary["views"]["all"]["validation"], 1)
            source = {r["id"]: r for r in map(json.loads, paths["canonical"].read_text().splitlines())}
            audits = {r["sample_id"]: r for r in map(json.loads, (root / "out" / "AUDIT.jsonl").read_text().splitlines())}
            for view in ("all", "provisional"):
                for category in ("train", "validation"):
                    rows = list(map(json.loads, (root / "out" / view / (category + "-inputs.jsonl")).read_text().splitlines()))
                    for row in rows:
                        sid = row["sample_id"]
                        verify_visible_messages(row["messages"], source[sid]["input_context"],
                                                expected_messages_hash=audits[sid]["messages_sha256"])
                        self.assertEqual(row["status"], "EXPERIMENTAL_OFFLINE_NES_CANDIDATE")
                        self.assertEqual(row["evaluation_role"], "validation-only" if category == "validation" else "train-candidate")
                    labels = list(map(json.loads, (root / "out" / view / (category + "-labels.jsonl")).read_text().splitlines()))
                    self.assertTrue(all(row["assistant_label"]["content"] == "" for row in labels))


if __name__ == "__main__":
    unittest.main()
