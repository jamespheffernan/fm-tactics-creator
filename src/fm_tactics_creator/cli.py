"""Portable command line for native tactic variants."""

import argparse
import json
import os
from pathlib import Path
import sys
from . import __version__
from .engine import MENTALITIES, create_tactic, inspect_template
from .destinations import plan_fm27_destination, tactics_directory, FM27_DIRECTORY_ENV


def _normalize(value):
    return value.casefold().replace("_", "-").replace(" ", "-")


def main():
    parser = argparse.ArgumentParser(
        prog="fm-tactics",
        description="Create a native .fmf variant from an existing template. No game process or save access.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "templates",
        help="Discover local FM27 native templates, or inspect a chosen directory.",
    )
    listing.add_argument("--directory", type=Path)
    listing.add_argument("--json", action="store_true")
    inspecting = commands.add_parser(
        "inspect", help="Inspect a native template and obtain its SHA256."
    )
    inspecting.add_argument("--template", type=Path, required=True)
    inspecting.add_argument("--json", action="store_true")
    creating = commands.add_parser(
        "create",
        help="Write a new native tactic and provenance sidecar; never overwrite files.",
    )
    creating.add_argument("--template", type=Path, required=True)
    creating.add_argument(
        "--template-sha256", help="Reject a template changed since inspection."
    )
    destination = creating.add_mutually_exclusive_group(required=True)
    destination.add_argument(
        "--output", type=Path, help="Explicit new .fmf output path."
    )
    destination.add_argument(
        "--fm27-folder",
        action="store_true",
        help="Save a new tactic directly in your FM27 tactics folder; requires --name.",
    )
    creating.add_argument(
        "--tactics-dir",
        help="Existing custom FM27 tactics directory; valid only with --fm27-folder. Overrides FM27_TACTICS_DIR.",
    )
    creating.add_argument(
        "--preview",
        action="store_true",
        help="Inspect the template and report exact destination paths without writing.",
    )
    creating.add_argument(
        "--name", help="New tactic name; defaults to the output filename stem."
    )
    creating.add_argument(
        "--mentality", choices=[_normalize(v) for v in MENTALITIES.values()]
    )
    creating.add_argument(
        "--tackling",
        choices=["get-stuck-in", "stay-on-feet", "none"],
        help="Omit to inherit. none clears both explicit tackling flags; it does not assert a UI default.",
    )
    creating.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "templates":
            if args.directory:
                directories = [args.directory.expanduser()]
                if not directories[0].is_dir():
                    raise ValueError(
                        f"Template directory does not exist: {directories[0]}"
                    )
            elif FM27_DIRECTORY_ENV in os.environ:
                directories = [tactics_directory()]
            else:
                home = Path.home()
                directories = [
                    home
                    / "Library/Application Support/Sports Interactive/Football Manager 27/Tactics",
                    home / "Documents/Sports Interactive/Football Manager 27/tactics",
                    home
                    / ".local/share/Sports Interactive/Football Manager 27/tactics",
                ]
            templates, excluded = [], []
            seen = set()
            for directory in directories:
                if not directory.is_dir():
                    continue
                for path in sorted(directory.iterdir()):
                    if path.suffix.lower() != ".fmf" or path.resolve() in seen:
                        continue
                    seen.add(path.resolve())
                    try:
                        templates.append(inspect_template(path))
                    except Exception as error:
                        excluded.append({"path": str(path), "error": str(error)})
            result = {
                "templates": templates,
                "excluded": excluded,
                "searched_directories": [str(p) for p in directories],
                "supported_edits": ["name", "mentality", "team_tackling"],
            }
        elif args.command == "inspect":
            result = inspect_template(args.template)
        else:
            if args.tactics_dir is not None and not args.fm27_folder:
                raise ValueError("--tactics-dir requires --fm27-folder.")
            if args.fm27_folder and not args.name:
                raise ValueError("--fm27-folder requires --name.")
            name = args.name if args.fm27_folder else args.name or args.output.stem
            if (
                not name.strip()
                or len(name.encode("utf-8")) > 120
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
            ):
                raise ValueError("Name must contain 1 to 120 printable UTF-8 bytes.")
            plan = (
                plan_fm27_destination(name, args.tactics_dir)
                if args.fm27_folder
                else {
                    "destination_mode": "explicit_output",
                    "output_path": str(args.output.expanduser().absolute()),
                    "receipt_path": str(
                        args.output.expanduser().absolute().with_suffix(".receipt.json")
                    ),
                }
            )
            mentality = next(
                (v for v in MENTALITIES.values() if _normalize(v) == args.mentality),
                None,
            )
            tackling = {
                "get-stuck-in": "Get Stuck In",
                "stay-on-feet": "Stay On Feet",
                "none": "No explicit selection",
            }.get(args.tackling)
            if args.preview:
                source = inspect_template(args.template)
                if (
                    args.template_sha256 is not None
                    and args.template_sha256 != source["template_sha256"]
                ):
                    raise ValueError(
                        "Template SHA256 changed or does not match. Inspect the template again."
                    )
                for destination_path in (plan["output_path"], plan["receipt_path"]):
                    path = Path(destination_path)
                    if path.exists() or path.is_symlink():
                        raise FileExistsError(
                            f"Refusing to overwrite existing file: {path}"
                        )
                result = {
                    "status": "preview",
                    **plan,
                    "name": name,
                    "template_path": source["template_path"],
                    "template_sha256": source["template_sha256"],
                    "mentality": mentality or source["mentality"],
                    "team_tackling": tackling or source["team_tackling"],
                    "files_created": False,
                }
            else:
                result = create_tactic(
                    template=args.template,
                    output=plan["output_path"],
                    name=name,
                    mentality=mentality,
                    team_tackling=tackling,
                    expected_sha256=args.template_sha256,
                    receipt=plan["receipt_path"] if args.fm27_folder else None,
                    destination_metadata=plan if args.fm27_folder else None,
                )
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "create" and args.preview:
            print(
                f"Preview: {result['output_path']}\nReceipt: {result['receipt_path']}\nNo files created."
            )
        elif args.command == "create":
            print(
                f"Created {result['output_path']}\nName: {result['name']}\nMentality: {result['mentality']}\nTackling: {result['team_tackling']}\nReceipt: {result['receipt_path']}\nNative archive roundtrip passed. Interactive FM import was not tested by this command."
            )
        elif args.command == "inspect":
            print(
                f"{result['name']}\nMentality: {result['mentality']}\nTackling: {result['team_tackling']}\nSHA256: {result['template_sha256']}"
            )
        else:
            for row in result["templates"]:
                print(f"{row['name']}\t{row['template_path']}")
            if not result["templates"]:
                print(
                    "No supported templates found. Supply --directory or use an explicit --template file."
                )
    except Exception as error:
        if args.json:
            print(
                json.dumps({"error": str(error), "type": type(error).__name__}),
                file=sys.stderr,
            )
        else:
            print(f"fm-tactics: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
