"""Explicit native tactic destinations; no game or process access."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unicodedata


FM27_DIRECTORY_ENV = "FM27_TACTICS_DIR"
RECEIPT_DIRECTORY = ".fm-tactics-receipts"


def default_tactics_directory() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return (
            home
            / "Library/Application Support/Sports Interactive/Football Manager 27/Tactics"
        )
    if sys.platform == "win32":
        return home / "Documents/Sports Interactive/Football Manager 27/tactics"
    if sys.platform.startswith("linux"):
        return home / ".local/share/Sports Interactive/Football Manager 27/tactics"
    raise ValueError(
        "FM27's tactics folder is unknown on this platform. Supply --tactics-dir."
    )


def tactics_directory(override: str | Path | None = None) -> Path:
    configured = (
        override if override is not None else os.environ.get(FM27_DIRECTORY_ENV)
    )
    if configured is not None:
        if not str(configured).strip():
            raise ValueError("The configured FM27 tactics directory must not be empty.")
        folder = Path(configured).expanduser().resolve(strict=True)
        if not folder.is_dir():
            raise ValueError(
                "The configured FM27 tactics directory must be an existing directory."
            )
        return folder
    folder = default_tactics_directory()
    if folder.exists():
        if not folder.is_dir():
            raise ValueError("FM27's tactics path exists but is not a directory.")
        return folder.resolve(strict=True)
    if folder.is_symlink() or not folder.parent.is_dir():
        raise ValueError(
            "FM27's user data folder was not found. Supply --tactics-dir or FM27_TACTICS_DIR; no alternate folder was selected."
        )
    # Create this one child only when an actual write follows. Preview stays read-only.
    return folder.parent.resolve(strict=True) / folder.name


def safe_tactic_filename(name: str) -> str:
    if (
        len(name.encode("utf-8")) > 120
        or not name.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError("Folder mode requires a printable tactic name.")
    normalized = unicodedata.normalize("NFKC", name).strip()
    if "/" in normalized or "\\" in normalized or normalized in (".", ".."):
        raise ValueError(
            "Tactic names used as filenames must not contain path separators or traversal components."
        )
    stem = "".join(
        char if char.isalnum() or char in " -_" else "-" for char in normalized
    ).strip(" .-_")
    while len(stem.encode("utf-8")) > 100:
        stem = stem[:-1]
    stem = stem.rstrip(" .-_")
    if not stem:
        raise ValueError("Tactic name does not produce a usable filename.")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if stem.casefold() in reserved:
        raise ValueError(
            "Tactic name produces a reserved filename. Choose another name."
        )
    return stem + ".fmf"


def _filename_identity(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold().rstrip(" .")


def plan_fm27_destination(name: str, override: str | Path | None = None) -> dict:
    folder = tactics_directory(override)
    filename = safe_tactic_filename(name)
    if folder.exists():
        identity = _filename_identity(filename)
        for existing in folder.iterdir():
            if _filename_identity(existing.name) == identity:
                raise FileExistsError(
                    f"Refusing to overwrite or duplicate an existing tactic filename: {existing}"
                )
    output = folder / filename
    receipt_folder = folder / RECEIPT_DIRECTORY
    if receipt_folder.is_symlink() or (
        receipt_folder.exists() and not receipt_folder.is_dir()
    ):
        raise ValueError(
            "FM27's receipt directory must be a real child directory, not a symlink or file."
        )
    receipt = receipt_folder / Path(filename).with_suffix(".receipt.json")
    if receipt.exists() or receipt.is_symlink():
        raise FileExistsError(
            f"Refusing to overwrite an existing tactic receipt: {receipt}"
        )
    return {
        "destination_mode": "fm27_folder",
        "tactics_directory": str(folder),
        "output_filename": filename,
        "output_path": str(output),
        "receipt_path": str(receipt),
    }
