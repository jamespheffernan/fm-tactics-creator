"""Standalone native tactic variants. No game process or checkout dependency."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

import zstandard as zstd
from ._codec.probe import probe, INNER_MAGIC, decompress_bounded
from ._codec.decode import parse_tac_plaintext
from ._codec.repack import (
    extract_member_plaintexts,
    repack_native_fmf,
    replace_tac_name,
    replace_mentality,
)

from .defensive_line import defensive_line_selection, replace_defensive_line, describe_defensive_line

MAX_TEMPLATE_BYTES = 16 * 1024 * 1024
MENTALITIES = {
    1: "Very Defensive",
    2: "Defensive",
    3: "Cautious",
    4: "Balanced",
    5: "Positive",
    6: "Attacking",
    7: "Very Attacking",
}
TACKLING_FLAGS = {"No explicit selection": 0, "Get Stuck In": 1, "Stay On Feet": 2}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source(path: Path) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(MAX_TEMPLATE_BYTES + 1)
    if not 26 <= len(data) <= MAX_TEMPLATE_BYTES:
        raise ValueError("Template size must be between 26 bytes and 16 MiB.")
    return data


def read_template(raw: str | Path) -> tuple[Path, bytes, dict[str, bytes]]:
    path = Path(raw).expanduser().resolve(strict=True)
    if path.suffix.lower() != ".fmf" or not path.is_file():
        raise ValueError("Template must be an existing .fmf file.")
    if not 26 <= path.stat().st_size <= MAX_TEMPLATE_BYTES:
        raise ValueError("Template size must be between 26 bytes and 16 MiB.")
    source = _read_source(path)
    with tempfile.TemporaryDirectory(prefix="fm-tactics-input-") as folder:
        snapshot = Path(folder) / "template.fmf"
        snapshot.write_bytes(source)
        members = extract_member_plaintexts(snapshot)
    if ".tac" not in members or ".aom" not in members:
        raise ValueError("Template requires native .tac and .aom members.")
    tac = members[".tac"]
    if (
        len(tac) < 20
        or tac[:10] != bytes.fromhex("03016361742e22002244")
        or tac[11] not in (26, 27)
    ):
        raise ValueError(
            "Unsupported native tactic version. Use a current FM27-generation template (cat. 0x44, source major 26 or 27)."
        )
    return path, source, members


def tackling_selection(tac: bytes) -> tuple[int, int]:
    setup = parse_tac_plaintext(tac).get("pre_style_setup", {})
    offset = setup.get("team_instruction_vector_candidate_offset")
    if (
        not isinstance(offset, int)
        or setup.get("team_instruction_vector_candidate_size") != 12
        or offset + 12 > len(tac)
    ):
        raise ValueError("Unsupported native team instruction vector.")
    # Native FM27 serializes option bits 0..83 without remapping. Bits72/73
    # are Get Stuck In and Stay On Feet. Neither selected is not a UI default.
    value = tac[offset + 9] & 3
    if value == 3:
        raise ValueError("Template has contradictory stored tackling selections.")
    return offset + 9, value


def replace_tackling(tac: bytes, label: str) -> bytes:
    if label not in TACKLING_FLAGS:
        raise ValueError("Unsupported team tackling selection.")
    offset, _ = tackling_selection(tac)
    result = bytearray(tac)
    result[offset] = (result[offset] & ~3) | TACKLING_FLAGS[label]
    return bytes(result)


def inspect_template(path: str | Path) -> dict:
    template, source, members = read_template(path)
    tac = members[".tac"]
    parsed = parse_tac_plaintext(tac)
    name = parsed.get("name", {}).get("value")
    if not name:
        raise ValueError("Template has no readable native tactic name.")
    return {
        "template_path": str(template),
        "template_sha256": sha(source),
        "name": name,
        "source_game_major": tac[11],
        "native_header_hex": tac[:16].hex(),
        "mentality": MENTALITIES.get(
            parsed.get("pre_style_setup", {}).get("mentality_id")
        ),
        "team_tackling": next(
            label
            for label, value in TACKLING_FLAGS.items()
            if value == tackling_selection(tac)[1]
        ),
        "tactical_style": parsed.get("tactical_style", {}).get("value"),
        **describe_defensive_line(tac),
        "member_sizes": {key: len(value) for key, value in members.items()},
        "supported_edits": ["name", "mentality", "team_tackling"]
        + (["defensive_line"] if describe_defensive_line(tac)["defensive_line_state"] == "known" else []),
        "inherited": [
            "formations",
            "phase roles",
            "unrequested team instructions",
            "player instructions",
            "thumbnail",
        ],
        "game_load_verified": False,
    }


def _replace_string(data: bytes, offset: int, name: str, expected: str) -> bytes:
    old = expected.encode("utf-8")
    if (
        data[offset : offset + 4] != struct.pack("<I", len(old))
        or data[offset + 4 : offset + 4 + len(old)] != old
    ):
        raise ValueError("Native name reference does not match the tactic name.")
    encoded = name.encode("utf-8")
    return (
        data[:offset]
        + struct.pack("<I", len(encoded))
        + encoded
        + data[offset + 4 + len(old) :]
    )


def _synchronize_toc(path: Path, old: str, name: str) -> None:
    result = probe(path)
    data = path.read_bytes()
    toc = decompress_bounded(data[result["zstd_toc_offset"] :], 2_000_000)
    matches = [entry for entry in result["toc"]["strings"] if entry["text"] == old]
    if len(matches) != 2 or matches[0]["offset"] != 0:
        raise ValueError("Unsupported native tactic-name table layout.")
    for entry in reversed(matches):
        toc = _replace_string(toc, entry["offset"], name, old)
    path.write_bytes(
        data[: result["nested_fmf_offset"]]
        + INNER_MAGIC
        + zstd.ZstdCompressor(level=3).compress(toc)
    )


def create_tactic(
    *,
    template: str | Path,
    output: str | Path,
    name: str,
    mentality: str | None = None,
    team_tackling: str | None = None,
    defensive_line: str | None = None,
    expected_sha256: str | None = None,
    receipt: str | Path | None = None,
    destination_metadata: dict[str, str] | None = None,
) -> dict:
    if (
        not name.strip()
        or len(name.encode("utf-8")) > 120
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise ValueError("Name must contain 1 to 120 printable UTF-8 bytes.")
    name = name.strip()
    source_path, source, before = read_template(template)
    output_path = Path(output).expanduser().absolute()
    if output_path.suffix.lower() != ".fmf":
        raise ValueError("Output filename must end with .fmf.")
    receipt_path = (
        Path(receipt).expanduser().absolute()
        if receipt is not None
        else output_path.with_suffix(".receipt.json")
    )
    if receipt_path.resolve() in (source_path, output_path.resolve()):
        raise ValueError("Receipt must differ from the template and tactic output.")
    if source_path == output_path.resolve():
        raise ValueError("Output must differ from the template.")
    for path in (output_path, receipt_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    if expected_sha256 is not None and expected_sha256 != sha(source):
        raise ValueError(
            "Template SHA256 changed or does not match. Inspect the template again."
        )
    original = parse_tac_plaintext(before[".tac"])
    old_name = original["name"]["value"]
    tac = replace_tac_name(before[".tac"], name)
    if mentality is not None:
        if mentality not in MENTALITIES.values():
            raise ValueError("Unsupported mentality.")
        tac = replace_mentality(tac, mentality)
    if defensive_line is not None:
        tac = replace_defensive_line(tac, defensive_line)
    if team_tackling is not None:
        tac = replace_tackling(tac, team_tackling)
    aom = before[".aom"]
    handler = b"TACTICS_TYPE_HANDLER"
    if (
        aom[:8] != bytes.fromhex("03016d6f612e0400")
        or aom[12 : 12 + len(handler)] != handler
    ):
        raise ValueError("Unsupported native tactic details member.")
    aom = _replace_string(aom, 12 + len(handler), name, old_name)
    with tempfile.TemporaryDirectory(prefix="fm-tactics-") as folder:
        candidate = Path(folder) / "candidate.fmf"
        snapshot = Path(folder) / "template.fmf"
        snapshot.write_bytes(source)
        repack_native_fmf(
            snapshot, candidate, plaintext_overrides={".tac": tac, ".aom": aom}
        )
        _synchronize_toc(candidate, old_name, name)
        after = extract_member_plaintexts(candidate)
        if set(after) != set(before) or after[".tac"] != tac or after[".aom"] != aom:
            raise ValueError("Native member roundtrip failed.")
        if any(
            after[key] != before[key] for key in before if key not in (".tac", ".aom")
        ):
            raise ValueError("An unrequested native member changed.")
        restored = replace_tac_name(after[".tac"], old_name)
        if mentality is not None:
            restored = replace_mentality(
                restored, MENTALITIES[original["pre_style_setup"]["mentality_id"]]
            )
        if defensive_line is not None:
            restored = replace_defensive_line(restored, defensive_line_selection(before[".tac"])[1])
        if team_tackling is not None:
            original_tackling = next(
                label
                for label, value in TACKLING_FLAGS.items()
                if value == tackling_selection(before[".tac"])[1]
            )
            restored = replace_tackling(restored, original_tackling)
        if restored != before[".tac"]:
            raise ValueError("An unrequested tactic byte changed.")
        if _read_source(source_path) != source:
            raise ValueError("Template changed during generation. No output delivered.")
        blob = candidate.read_bytes()
    parsed = parse_tac_plaintext(tac)
    result = {
        "status": "native_archive_written_and_roundtrip_verified",
        "output_path": str(output_path),
        "receipt_path": str(receipt_path),
        "output_sha256": sha(blob),
        "output_bytes": len(blob),
        "template_path": str(source_path),
        "template_sha256": sha(source),
        "name": name,
        "source_game_major": tac[11],
        "native_header_hex": tac[:16].hex(),
        "mentality": MENTALITIES.get(parsed["pre_style_setup"]["mentality_id"]),
        "team_tackling": next(
            label
            for label, value in TACKLING_FLAGS.items()
            if value == tackling_selection(tac)[1]
        ),
        **describe_defensive_line(tac),
        "defensive_line_mode": "inherit" if defensive_line is None else "explicit_change",
        "edits": ["name"]
        + (["mentality"] if mentality is not None else [])
        + (["team_tackling"] if team_tackling is not None else [])
        + (["defensive_line"] if defensive_line is not None else []),
        "verification": {
            "native_decode_roundtrip": True,
            "all_unrequested_tactic_bytes_preserved": True,
            "template_unchanged": True,
            "game_load_verified": False,
            "scope": "Local native archive roundtrip. Release QA separately validates generated bodies with the isolated FM27 native reader. This command does not launch FM or verify interactive import.",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if destination_metadata:
        for key in ("destination_mode", "tactics_directory", "output_filename"):
            if key in destination_metadata:
                result[key] = destination_metadata[key]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects both the tactic and its provenance sidecar.
    # A collision never overwrites an existing user file.
    created_receipt = False
    with output_path.open("xb") as artifact:
        try:
            with receipt_path.open("x", encoding="utf-8") as receipt:
                created_receipt = True
                artifact.write(blob)
                json.dump(result, receipt, ensure_ascii=False, indent=2)
                receipt.write("\n")
        except Exception:
            artifact.close()
            output_path.unlink(missing_ok=True)
            if created_receipt:
                receipt_path.unlink(missing_ok=True)
            raise
    return result
