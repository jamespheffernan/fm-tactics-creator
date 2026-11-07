"""Native tactic archive codec adapted from FM26 Deepener; see LICENSE and PROVENANCE.json."""

from __future__ import annotations
import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Any
import zstandard as zstd

OUTER_MAGIC = b"\x02\x01afe.\x08\x00\x00"
INNER_MAGIC = b"\x02\x01fmf.\x08\x00\x00"
ZSTD_MAGIC = b"(\xb5/\xfd"
ARCHIVE_HEADER_SIZE = 26
MEMBER_ENVELOPE_HEADER = b"\x10\x00\x00\x00\x10\x00\x00\x00"
MEMBER_ENVELOPE_LENGTH_FIELD_SIZE = 8
MEMBER_ENVELOPE_KEY_SIZE = 16
MEMBER_ENVELOPE_IV_SIZE = 16
MEMBER_ENVELOPE_CIPHERTEXT_OFFSET = (
    MEMBER_ENVELOPE_LENGTH_FIELD_SIZE
    + MEMBER_ENVELOPE_KEY_SIZE
    + MEMBER_ENVELOPE_IV_SIZE
)


def decompress_bounded(data: bytes, limit: int) -> bytes:
    declared = zstd.frame_content_size(data)
    if declared == zstd.CONTENTSIZE_ERROR:
        raise ValueError("Invalid Zstandard frame header.")
    if declared != zstd.CONTENTSIZE_UNKNOWN and declared > limit:
        raise ValueError("Declared decompressed size exceeds the supported limit.")
    raw = zstd.ZstdDecompressor().decompress(data, max_output_size=limit)
    if len(raw) > limit:
        raise ValueError("Decompressed payload exceeds the supported limit.")
    return raw


def read_u24_le(data: bytes, offset: int) -> int:
    return data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((count / total * math.log2(count / total) for count in counts.values()))


def parse_toc_atoms(data: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return a conservative stream of length-prefixed strings and u32 values."""
    strings: list[dict[str, Any]] = []
    numbers: list[dict[str, Any]] = []
    offset = 0
    while offset + 4 <= len(data):
        value = int.from_bytes(data[offset : offset + 4], "little")
        if 0 < value <= 256 and offset + 4 + value <= len(data):
            raw = data[offset + 4 : offset + 4 + value]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if text and all((ord(char) >= 32 and ord(char) != 127 for char in text)):
                strings.append({"offset": offset, "text": text, "length": value})
                offset += 4 + value
                continue
        numbers.append({"offset": offset, "u32": value})
        offset += 4
    return (strings, numbers)


def extension_records(
    toc: bytes, strings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in strings:
        text = item["text"]
        if not text.startswith("."):
            continue
        after = int(item["offset"]) + 4 + int(item["length"])
        u64s = []
        for idx in range(6):
            pos = after + idx * 8
            if pos + 8 <= len(toc):
                u64s.append(int.from_bytes(toc[pos : pos + 8], "little"))
        records.append(
            {"offset": item["offset"], "extension": text, "following_u64": u64s}
        )
    return records


def parse_member_envelope(member: bytes, raw_size: int | None) -> dict[str, Any]:
    """Describe the clear per-member wrapper without claiming tactic semantics."""
    header_u32_le = []
    if len(member) >= 8:
        header_u32_le = [
            int.from_bytes(member[0:4], "little"),
            int.from_bytes(member[4:8], "little"),
        ]
    out: dict[str, Any] = {
        "header_hex": member[:8].hex(),
        "header_u32_le": header_u32_le,
        "starts_with_16_16_header": member.startswith(MEMBER_ENVELOPE_HEADER),
    }
    if not member.startswith(MEMBER_ENVELOPE_HEADER):
        out["candidate_model"] = "unknown_or_unwrapped_member"
        return out
    if len(member) < MEMBER_ENVELOPE_CIPHERTEXT_OFFSET:
        out["candidate_model"] = "16_16_header_but_too_short_for_key_iv_ciphertext"
        return out
    ciphertext_size = len(member) - MEMBER_ENVELOPE_CIPHERTEXT_OFFSET
    out.update(
        {
            "candidate_model": "8_byte_key_iv_lengths_plus_key16_iv16_ciphertext",
            "key_length_offset_in_member": 0,
            "iv_length_offset_in_member": 4,
            "key_offset_in_member": MEMBER_ENVELOPE_LENGTH_FIELD_SIZE,
            "key_size": MEMBER_ENVELOPE_KEY_SIZE,
            "key_sha256_hint": hashlib.sha256(
                member[
                    MEMBER_ENVELOPE_LENGTH_FIELD_SIZE : MEMBER_ENVELOPE_LENGTH_FIELD_SIZE
                    + MEMBER_ENVELOPE_KEY_SIZE
                ]
            ).hexdigest(),
            "iv_offset_in_member": MEMBER_ENVELOPE_LENGTH_FIELD_SIZE
            + MEMBER_ENVELOPE_KEY_SIZE,
            "iv_size": MEMBER_ENVELOPE_IV_SIZE,
            "iv_sha256_hint": hashlib.sha256(
                member[
                    MEMBER_ENVELOPE_LENGTH_FIELD_SIZE
                    + MEMBER_ENVELOPE_KEY_SIZE : MEMBER_ENVELOPE_CIPHERTEXT_OFFSET
                ]
            ).hexdigest(),
            "ciphertext_offset_in_member": MEMBER_ENVELOPE_CIPHERTEXT_OFFSET,
            "ciphertext_size": ciphertext_size,
            "candidate_body_offset_in_member": MEMBER_ENVELOPE_CIPHERTEXT_OFFSET,
            "candidate_body_size": ciphertext_size,
            "candidate_overhead_size": MEMBER_ENVELOPE_CIPHERTEXT_OFFSET,
        }
    )
    if raw_size:
        out["ciphertext_to_raw_ratio"] = round(ciphertext_size / raw_size, 4)
        out["ciphertext_minus_raw_size"] = ciphertext_size - raw_size
        out["candidate_body_to_raw_ratio"] = round(ciphertext_size / raw_size, 4)
        out["candidate_body_minus_raw_size"] = ciphertext_size - raw_size
    return out


def member_layout(
    data: bytes, nested_offset: int, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for record in records:
        values = record.get("following_u64", [])
        if not isinstance(values, list) or len(values) < 3:
            continue
        logical_offset = int(values[0])
        stored_size = int(values[1])
        raw_size = int(values[2])
        offset = ARCHIVE_HEADER_SIZE + logical_offset
        end = offset + stored_size
        if stored_size < 0 or end > nested_offset:
            members.append(
                {
                    "extension": record["extension"],
                    "logical_data_offset": logical_offset,
                    "offset": offset,
                    "stored_size": stored_size,
                    "raw_size_from_toc": raw_size,
                    "layout_status": "out_of_bounds",
                }
            )
            continue
        member = data[offset:end]
        members.append(
            {
                "extension": record["extension"],
                "logical_data_offset": logical_offset,
                "offset": offset,
                "stored_size": stored_size,
                "raw_size_from_toc": raw_size,
                "entropy_bits_per_byte": round(entropy(member), 4),
                "sha256_hint": hashlib.sha256(member).hexdigest(),
                "envelope": parse_member_envelope(member, raw_size),
                "layout_status": "ok",
            }
        )
    covered: list[tuple[int, int]] = []
    for member in members:
        if member.get("layout_status") != "ok":
            continue
        start = int(member["offset"])
        covered.append((start, start + int(member["stored_size"])))
    covered.sort()
    cursor = ARCHIVE_HEADER_SIZE
    for start, end in covered:
        if start > cursor:
            members.append(
                {
                    "extension": "_layout_gap",
                    "offset": cursor,
                    "stored_size": start - cursor,
                    "raw_size_from_toc": None,
                    "layout_status": "gap_or_unparsed_member_region",
                }
            )
        elif start < cursor:
            members.append(
                {
                    "extension": "_layout_overlap",
                    "offset": start,
                    "stored_size": cursor - start,
                    "raw_size_from_toc": None,
                    "layout_status": "overlapping_member_region",
                }
            )
        cursor = max(cursor, end)
    if cursor != nested_offset:
        members.append(
            {
                "extension": "_layout_gap",
                "offset": cursor,
                "stored_size": nested_offset - cursor,
                "raw_size_from_toc": None,
                "layout_status": "gap_or_unparsed_trailer",
            }
        )
    return sorted(
        members,
        key=lambda item: (
            int(item.get("offset") or 0),
            str(item.get("extension") or ""),
        ),
    )


def probe(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    result: dict[str, Any] = {
        "path": str(path),
        "size": len(data),
        "outer_magic": data[: len(OUTER_MAGIC)].hex(),
        "format_guess": "unknown",
    }
    if not data.startswith(OUTER_MAGIC) or len(data) < 18:
        return result
    result["format_guess"] = "si-afe-archive"
    outer_payload_len = read_u24_le(data, 9)
    nested_offset = 9 + outer_payload_len
    zstd_offset = data.find(ZSTD_MAGIC, nested_offset)
    result.update(
        {
            "outer_payload_len_u24_at_0x09": outer_payload_len,
            "nested_fmf_offset": nested_offset,
            "nested_header_ok": data[nested_offset : nested_offset + len(INNER_MAGIC)]
            == INNER_MAGIC,
            "zstd_toc_offset": zstd_offset,
            "member_data_base_offset": ARCHIVE_HEADER_SIZE,
            "member_offset_formula": "member.offset = member_data_base_offset + toc_extension_record.following_u64[0]",
        }
    )
    if zstd_offset < 0:
        return result
    toc = decompress_bounded(data[zstd_offset:], 2000000)
    strings, numbers = parse_toc_atoms(toc)
    records = extension_records(toc, strings)
    result["toc"] = {
        "decompressed_size": len(toc),
        "sha256_hint": hashlib.sha256(toc).hexdigest(),
        "strings": strings,
        "first_numbers": numbers[:24],
        "extension_records": records,
    }
    encoded_region = data[ARCHIVE_HEADER_SIZE:nested_offset]
    result["encoded_region"] = {
        "offset": ARCHIVE_HEADER_SIZE,
        "size": len(encoded_region),
        "entropy_bits_per_byte": round(entropy(encoded_region), 4),
        "sha256_hint": hashlib.sha256(encoded_region).hexdigest(),
    }
    members = member_layout(data, nested_offset, records)
    result["members"] = members
    return result


def validated_probe(path: Path) -> dict[str, Any]:
    result = probe(path)
    nested = result.get("nested_fmf_offset")
    if (
        result.get("nested_header_ok") is not True
        or not isinstance(nested, int)
        or nested < ARCHIVE_HEADER_SIZE
    ):
        raise ValueError("Missing or invalid native inner archive header.")
    if result.get("zstd_toc_offset") != nested + len(INNER_MAGIC):
        raise ValueError("Unsupported native table-of-contents boundary.")
    members = result.get("members") or []
    records = result.get("toc", {}).get("extension_records") or []
    if (
        not members
        or len(members) != len(records)
        or any(member.get("layout_status") != "ok" for member in members)
    ):
        raise ValueError(
            "Unsupported, incomplete or overlapping native archive layout."
        )
    extensions = [member.get("extension") for member in members]
    if len(set(extensions)) != len(extensions):
        raise ValueError("Duplicate native member extensions are unsupported.")
    if not {".tac", ".aom"} <= set(extensions) or not set(extensions) <= {
        ".tac",
        ".aom",
        ".img",
    }:
        raise ValueError("Unsupported native tactic member set.")
    if any(
        member["stored_size"] <= 0 or member["raw_size_from_toc"] > 64 * 1024 * 1024
        for member in members
    ):
        raise ValueError("Native member size exceeds the supported layout limits.")
    return result
