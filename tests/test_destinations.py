import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fm_tactics_creator import cli, destinations


class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name).resolve()
        self.environment = patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        os.environ.pop(destinations.FM27_DIRECTORY_ENV, None)
        self.home_patch = patch.object(
            destinations.Path, "home", return_value=self.home
        )
        self.platform_patch = patch.object(destinations.sys, "platform", "darwin")
        self.home_patch.start()
        self.platform_patch.start()
        self.folder = (
            self.home
            / "Library/Application Support/Sports Interactive/Football Manager 27/Tactics"
        )

    def tearDown(self):
        self.platform_patch.stop()
        self.home_patch.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def test_platform_defaults(self):
        self.assertEqual(destinations.default_tactics_directory(), self.folder)
        with patch.object(destinations.sys, "platform", "win32"):
            self.assertEqual(
                destinations.default_tactics_directory(),
                self.home / "Documents/Sports Interactive/Football Manager 27/tactics",
            )
        with patch.object(destinations.sys, "platform", "linux"):
            self.assertEqual(
                destinations.default_tactics_directory(),
                self.home
                / ".local/share/Sports Interactive/Football Manager 27/tactics",
            )

    def test_missing_game_parent_refuses_without_fallback(self):
        fallback = (
            self.home / "Documents/Sports Interactive/Football Manager 27/tactics"
        )
        fallback.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "no alternate folder"):
            destinations.plan_fm27_destination("New Tactic")
        self.assertFalse(self.folder.exists())

    def test_default_leaf_can_be_planned_without_creation(self):
        self.folder.parent.mkdir(parents=True)
        result = destinations.plan_fm27_destination("New Ç Tactic")
        self.assertEqual(Path(result["output_path"]), self.folder / "New Ç Tactic.fmf")
        self.assertFalse(self.folder.exists())

    def test_override_is_exact_existing_tactics_directory(self):
        custom = self.home / "custom"
        custom.mkdir()
        os.environ[destinations.FM27_DIRECTORY_ENV] = str(custom)
        self.assertEqual(destinations.tactics_directory(), custom)
        explicit = self.home / "explicit"
        explicit.mkdir()
        self.assertEqual(destinations.tactics_directory(explicit), explicit)
        with self.assertRaises(FileNotFoundError):
            destinations.tactics_directory(self.home / "missing")

    def test_filename_rejects_traversal_and_reserved_names(self):
        for name in (
            "../escape",
            "..\\escape",
            ".",
            "..",
            "...",
            "CON",
            "LPT1",
            "／escape",
            "a\nb",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                destinations.safe_tactic_filename(name)
        self.assertEqual(destinations.safe_tactic_filename("Ｆｏｏ:Ç?"), "Foo-Ç.fmf")
        self.assertLessEqual(
            len(Path(destinations.safe_tactic_filename("é" * 60)).stem.encode()), 100
        )

    def test_normalized_casefold_collision_and_receipt_links_fail(self):
        self.folder.mkdir(parents=True)
        old = self.folder / "FOO.fmf"
        old.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            destinations.plan_fm27_destination("Ｆｏｏ")
        self.assertEqual(old.read_bytes(), b"preserve")
        outside = self.home / "outside"
        outside.mkdir()
        receipt_folder = self.folder / destinations.RECEIPT_DIRECTORY
        receipt_folder.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "real child directory"):
            destinations.plan_fm27_destination("Other")
        receipt_folder.unlink()
        receipt_folder.write_text("preserve file")
        with self.assertRaisesRegex(ValueError, "real child directory"):
            destinations.plan_fm27_destination("Other")


@unittest.skipUnless(
    os.environ.get("FM_TACTICS_TEST_TEMPLATE"),
    "Supply an owned native template with FM_TACTICS_TEST_TEMPLATE",
)
class FolderCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.template = self.root / "source.fmf"
        self.original = Path(os.environ["FM_TACTICS_TEST_TEMPLATE"]).read_bytes()
        self.template.write_bytes(self.original)
        self.folder = self.root / "Tactics"
        self.folder.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(cli.sys, "argv", ["fm-tactics", *map(str, arguments)]),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = cli.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def create_args(self):
        return (
            "create",
            "--template",
            self.template,
            "--fm27-folder",
            "--tactics-dir",
            self.folder,
            "--name",
            "Portable Ç Positive",
            "--mentality",
            "positive",
            "--tackling",
            "stay-on-feet",
            "--json",
        )

    def test_preview_then_write_hidden_receipt_and_listing(self):
        before = sorted(self.root.rglob("*"))
        code, text, error = self.call(*self.create_args(), "--preview")
        self.assertEqual(code, 0, error)
        preview = json.loads(text)
        self.assertEqual(preview["status"], "preview")
        self.assertFalse(preview["files_created"])
        self.assertEqual(sorted(self.root.rglob("*")), before)
        code, text, error = self.call(*self.create_args())
        self.assertEqual(code, 0, error)
        result = json.loads(text)
        self.assertEqual(
            Path(result["output_path"]), self.folder / "Portable Ç Positive.fmf"
        )
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text()), result)
        self.assertEqual(
            Path(result["receipt_path"]).parent, self.folder / ".fm-tactics-receipts"
        )
        self.assertEqual(self.template.read_bytes(), self.original)
        with patch.dict(
            os.environ, {destinations.FM27_DIRECTORY_ENV: str(self.folder)}
        ):
            code, text, error = self.call("templates", "--json")
        self.assertEqual(code, 0, error)
        self.assertEqual(
            [row["name"] for row in json.loads(text)["templates"]],
            ["Portable Ç Positive"],
        )
        self.assertEqual(self.call(*self.create_args())[0], 2)

    def test_output_mode_retains_adjacent_receipt(self):
        output = self.root / "explicit.fmf"
        with patch.dict(
            os.environ, {destinations.FM27_DIRECTORY_ENV: str(self.root / "missing")}
        ):
            code, text, error = self.call(
                "create", "--template", self.template, "--output", output, "--json"
            )
        self.assertEqual(code, 0, error)
        result = json.loads(text)
        self.assertEqual(
            Path(result["receipt_path"]), self.root / "explicit.receipt.json"
        )
        self.assertNotIn("destination_mode", result)
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text()), result)

    def test_folder_name_required_and_tactics_dir_scoped(self):
        code, _, _ = self.call(
            "create",
            "--template",
            self.template,
            "--fm27-folder",
            "--tactics-dir",
            self.folder,
            "--json",
        )
        self.assertEqual(code, 2)
        code, _, _ = self.call(
            "create",
            "--template",
            self.template,
            "--output",
            self.root / "x.fmf",
            "--tactics-dir",
            self.folder,
            "--json",
        )
        self.assertEqual(code, 2)
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
