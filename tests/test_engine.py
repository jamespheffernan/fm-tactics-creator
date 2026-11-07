import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import zstandard
from fm_tactics_creator import engine
from fm_tactics_creator._codec.probe import decompress_bounded, probe, INNER_MAGIC


class BoundsTests(unittest.TestCase):
    def test_declared_zstd_size_is_rejected_before_decompression(self):
        frame = zstandard.ZstdCompressor().compress(b"x" * 1025)
        with self.assertRaisesRegex(ValueError, "Declared decompressed size"):
            decompress_bounded(frame, 1024)


@unittest.skipUnless(
    os.environ.get("FM_TACTICS_TEST_TEMPLATE"),
    "Supply an owned native template with FM_TACTICS_TEST_TEMPLATE",
)
class NativeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source.fmf"
        self.original = Path(os.environ["FM_TACTICS_TEST_TEMPLATE"]).read_bytes()
        self.source.write_bytes(self.original)
        self.output = self.root / "generated.fmf"

    def tearDown(self):
        self.directory.cleanup()

    def create(self, **changes):
        params = dict(
            template=self.source,
            output=self.output,
            name="Portable Ç Native",
            mentality="Positive",
            team_tackling="Stay On Feet",
        )
        params.update(changes)
        return engine.create_tactic(**params)

    def test_native_roundtrip_and_input_preservation(self):
        result = self.create(expected_sha256=hashlib.sha256(self.original).hexdigest())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(
            engine.inspect_template(self.output)["team_tackling"], "Stay On Feet"
        )
        self.assertTrue(
            result["verification"]["all_unrequested_tactic_bytes_preserved"]
        )
        self.assertFalse(result["verification"]["game_load_verified"])

    def test_defensive_line_changes_and_omission_read_back(self):
        for i, label in enumerate([None, "Higher Defensive Line", "No explicit selection"]):
            self.output = self.root / f"line-{i}.fmf"
            result = self.create(defensive_line=label)
            expected = label if label is not None else engine.inspect_template(self.source)["defensive_line"]
            self.assertEqual(result["defensive_line"], expected)
            self.assertEqual(engine.inspect_template(self.output)["defensive_line"], expected)
            self.assertEqual(result["defensive_line_mode"], "inherit" if label is None else "explicit_change")
            self.assertEqual("defensive_line" in result["edits"], label is not None)
            self.assertTrue(result["verification"]["all_unrequested_tactic_bytes_preserved"])

    def test_conflicting_height_preserves_unrelated_operations_and_rejects_edit(self):
        import json
        import subprocess
        import sys
        members = engine.read_template(self.source)[2]
        offset, _ = engine.defensive_line_selection(members[".tac"])
        tac = bytearray(members[".tac"])
        tac[offset] = (tac[offset] & 0xF0) | 3
        contradictory = self.root / "conflicting.fmf"
        engine.repack_native_fmf(self.source, contradictory, plaintext_overrides={".tac": bytes(tac)})
        self.source = contradictory
        inspection = engine.inspect_template(self.source)
        self.assertIsNone(inspection["defensive_line"])
        self.assertEqual(inspection["defensive_line_state"], "conflicting_stored_selections")
        self.assertNotIn("defensive_line", inspection["supported_edits"])
        result = self.create()
        self.assertIsNone(result["defensive_line"])
        self.assertEqual(result["defensive_line_mode"], "inherit")
        self.assertTrue(result["verification"]["all_unrequested_tactic_bytes_preserved"])
        with self.assertRaisesRegex(ValueError, "contradictory"):
            self.create(output=self.root / "changed.fmf", defensive_line="Higher Defensive Line")
        for extra, expected in [([], 0), (["--defensive-line", "higher"], 2)]:
            run = subprocess.run([sys.executable, "-m", "fm_tactics_creator", "create",
                "--template", str(self.source), "--output", str(self.root / "preview.fmf"),
                "--preview", "--json", *extra], capture_output=True, text=True)
            self.assertEqual(run.returncode, expected, run.stderr)
            if expected == 0:
                self.assertIsNone(json.loads(run.stdout)["defensive_line"])
            self.assertFalse((self.root / "preview.fmf").exists())

    def test_existing_output_or_receipt_is_preserved(self):
        self.output.write_bytes(b"keep output")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(self.output.read_bytes(), b"keep output")
        self.output.unlink()
        receipt = self.output.with_suffix(".receipt.json")
        receipt.write_text("keep receipt")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(receipt.read_text(), "keep receipt")
        self.assertFalse(self.output.exists())

    def test_failed_receipt_write_removes_only_new_pair(self):
        with patch.object(
            engine.json, "dump", side_effect=OSError("fixture disk write failure")
        ):
            with self.assertRaises(OSError):
                self.create()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".receipt.json").exists())

    def test_repack_uses_exact_hashed_snapshot(self):
        original_repack = engine.repack_native_fmf

        def repack(snapshot, output, **kwargs):
            self.assertNotEqual(Path(snapshot), self.source)
            self.assertEqual(Path(snapshot).read_bytes(), self.original)
            self.source.write_bytes(b"transient replacement")
            try:
                return original_repack(snapshot, output, **kwargs)
            finally:
                self.source.write_bytes(self.original)

        with patch.object(engine, "repack_native_fmf", repack):
            result = self.create()
        self.assertTrue(result["verification"]["native_decode_roundtrip"])

    def test_bad_inner_header_and_duplicate_members_fail_closed(self):
        metadata = probe(self.source)
        nested = metadata["nested_fmf_offset"]
        bad_header = bytearray(self.original)
        bad_header[nested + 2] ^= 1
        self.source.write_bytes(bad_header)
        with self.assertRaisesRegex(ValueError, "inner archive header"):
            engine.inspect_template(self.source)
        toc = decompress_bounded(
            self.original[metadata["zstd_toc_offset"] :], 2_000_000
        )
        self.assertIn(b".img", toc)
        duplicate = toc.replace(b".tac", b".img", 1)
        self.source.write_bytes(
            self.original[:nested]
            + INNER_MAGIC
            + zstandard.ZstdCompressor().compress(duplicate)
        )
        with self.assertRaisesRegex(ValueError, "Duplicate native member"):
            engine.inspect_template(self.source)

    def test_hash_mismatch_creates_no_output(self):
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.create(expected_sha256="0" * 64)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
