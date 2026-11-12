import json
import unittest

from nes_converter.prompt.json_context import CONTRACT, decode_body, encode_body


class FramingTests(unittest.TestCase):
    def test_manual_exact_wire_fixture(self):
        body = '<>\n"\t\\'
        expected = (
            '{"schema":"nes-related-context-json-v1","text":"'
            r'\u003c\u003e\n\"\t\\' + '"}'
        )
        self.assertEqual(encode_body(body), expected)
        self.assertEqual(decode_body(expected), body)

    def test_all_old_wrappers_are_literal_data(self):
        for body in (
            "<|recently_viewed_code_snippets|>",
            "<|/recently_viewed_code_snippets|>",
            "-----BEGIN OPAQUE RELATED CONTEXT-----",
            "-----END OPAQUE RELATED CONTEXT-----",
            '<|context_file|> phantom.ts\n<|snippet|>\nreturn `unfinished',
            "\n \t\n\u4e2d\U0001f600\r\n\n ",
            r'\u003c\n\\' + '"}]' + "\x00",
            "",
        ):
            with self.subTest(body=repr(body)):
                wire = encode_body(body)
                self.assertEqual(json.loads(wire)["text"], body)
                self.assertEqual(decode_body(wire).encode("utf-8"), body.encode("utf-8"))
                self.assertNotIn("<", wire)
                self.assertNotIn(">", wire)
                self.assertNotIn("\n", wire)
                self.assertNotIn("\r", wire)
                self.assertTrue(wire.isascii())

    def test_literal_escape_is_not_reinterpreted_as_source_character(self):
        self.assertNotEqual(encode_body("<"), encode_body(r"\u003c"))
        self.assertEqual(decode_body(encode_body(r"\u003c")), r"\u003c")
        self.assertNotEqual(encode_body("\n"), encode_body(r"\n"))

    def test_noncanonical_duplicate_and_invalid_payloads_fail(self):
        good = encode_body("hello")
        for payload in (
            good + "garbage", good + "\n", good[:-1], good.replace(CONTRACT, "unknown-v2"),
            good.replace('"text":"hello"', '"text":"hello","text":"changed"'),
            good.replace('"text":"hello"', '"text":null'),
            good.replace('"text":"hello"', '"text":"hello","extra":1'),
            '["hello"]', '{"schema":"' + CONTRACT + '","text":"<"}',
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decode_body(payload)

    def test_unpaired_surrogate_and_non_string_fail(self):
        for body in ("\ud800", "\udfff", None, 1):
            with self.subTest(body=repr(body)):
                with self.assertRaises(ValueError):
                    encode_body(body)


if __name__ == "__main__":
    unittest.main()
