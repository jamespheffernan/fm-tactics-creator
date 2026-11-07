"""Native tactic archive codec adapted from FM26 Deepener; see LICENSE and PROVENANCE.json."""

from __future__ import annotations
import hashlib
from typing import Any

CAT_TAC_MAGIC_AT_2 = b"cat."
STYLE_SENTINEL = b"IKITB"
STYLE_STRING_MAX_LENGTH = 8192
POST_STYLE_CODE_PREFIX = b"LLUNB"
TACTICAL_STYLE_MARKER_NEEDLES = (
    "Custom",
    "Tiki",
    "Gegen",
    "Counter",
    "Possession",
    "Catenaccio",
    "Park",
    "Wing",
    "Route",
    "Fluid",
    "Direct",
)
TEAM_INSTRUCTION_VECTOR_SIZE = 12
TACTIC_MENTALITIES_ENUM = {
    0: "None",
    1: "VeryDefensive",
    2: "Defensive",
    3: "Cautious",
    4: "Balanced",
    5: "Positive",
    6: "Attacking",
    7: "VeryAttacking",
}


def _decode_printable(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or any((ord(char) < 32 or ord(char) == 127 for char in text)):
        return None
    return text


def _read_len_prefixed_string(data: bytes, length_offset: int) -> dict[str, Any] | None:
    if length_offset < 0 or length_offset + 4 > len(data):
        return None
    length = int.from_bytes(data[length_offset : length_offset + 4], "little")
    start = length_offset + 4
    end = start + length
    if length <= 0 or length > 512 or end > len(data):
        return None
    text = _decode_printable(data[start:end])
    if text is None:
        return None
    return {
        "offset": length_offset,
        "length": length,
        "value": text,
        "end_exclusive": end,
    }


def _find_style_string(data: bytes) -> dict[str, Any] | None:
    style = _find_style_length_marker(data)
    if style:
        return style
    cursor = 0
    while True:
        sentinel = data.find(STYLE_SENTINEL, cursor)
        if sentinel < 0:
            return None
        for length_offset in range(max(0, sentinel - 516), sentinel - 3):
            item = _read_len_prefixed_string(data, length_offset)
            if item and item["end_exclusive"] == sentinel:
                prefix = length_offset - 1
                if prefix >= 0 and data[prefix] == 255:
                    item["prefix_offset"] = prefix
                    item["sentinel_offset"] = sentinel
                    return item
        cursor = sentinel + 1


def _find_style_length_marker(data: bytes) -> dict[str, Any] | None:
    for prefix in range(max(0, len(data) - 5)):
        if data[prefix] != 255:
            continue
        length_offset = prefix + 1
        length = int.from_bytes(data[length_offset : length_offset + 4], "little")
        start = length_offset + 4
        end = start + length
        if not 1 <= length <= STYLE_STRING_MAX_LENGTH or end > len(data):
            continue
        text = _decode_printable(data[start:end])
        if text is None:
            continue
        post_style_code = data[end : end + len(POST_STYLE_CODE_PREFIX)]
        has_post_style_code = post_style_code == POST_STYLE_CODE_PREFIX
        has_known_style_word = any(
            (
                needle.casefold() in text.casefold()
                for needle in TACTICAL_STYLE_MARKER_NEEDLES
            )
        )
        if not has_post_style_code and (not has_known_style_word):
            continue
        return {
            "offset": length_offset,
            "length": length,
            "value": text,
            "end_exclusive": end,
            "prefix_offset": prefix,
            "post_style_code_offset": end,
            "post_style_code_hex": data[end : end + 5].hex(" ")
            if end + 5 <= len(data)
            else "",
        }
    return None


def _pre_style_setup(data: bytes, style: dict[str, Any]) -> dict[str, Any]:
    vector_offset = int(style["prefix_offset"]) - TEAM_INSTRUCTION_VECTOR_SIZE
    setup: dict[str, Any] = {
        "style_prefix_offset": style["prefix_offset"],
        "style_sentinel_offset": style.get("sentinel_offset"),
        "post_style_code_offset": style.get("post_style_code_offset"),
        "post_style_code_hex": style.get("post_style_code_hex"),
    }
    if vector_offset >= 0:
        vector = data[vector_offset : vector_offset + TEAM_INSTRUCTION_VECTOR_SIZE]
        setup.update(
            {
                "team_instruction_vector_candidate_offset": vector_offset,
                "team_instruction_vector_candidate_size": TEAM_INSTRUCTION_VECTOR_SIZE,
                "team_instruction_vector_candidate_hex": vector.hex(" "),
            }
        )
    setup_offset = vector_offset - 6
    if setup_offset >= 0:
        raw = data[setup_offset:vector_offset]
        if len(raw) == 6:
            mentality_id = raw[2]
            setup.update(
                {
                    "setup_bytes_offset": setup_offset,
                    "setup_bytes_hex": raw.hex(" "),
                    "mentality_offset": setup_offset + 2,
                    "mentality_id": mentality_id,
                    "mentality_value": TACTIC_MENTALITIES_ENUM.get(mentality_id),
                    "mentality_enum_source": "FM.UI.TacticMentalities",
                }
            )
    return setup


def parse_tac_plaintext(data: bytes) -> dict[str, Any]:
    out = {
        "status": "unknown_plaintext",
        "size": len(data),
        "sha256_hint": hashlib.sha256(data).hexdigest(),
    }
    if len(data) < 6 or data[2:6] != CAT_TAC_MAGIC_AT_2:
        return out
    out.update(status="cat_tac_plaintext", magic_offset=2, magic="cat.")
    name = _read_len_prefixed_string(data, 16)
    if name:
        out["name"] = name
    style = _find_style_string(data)
    if style:
        out["tactical_style"] = style
        out["pre_style_setup"] = _pre_style_setup(data, style)
    return out
