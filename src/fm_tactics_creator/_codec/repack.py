"""Native tactic archive codec adapted from FM26 Deepener; see LICENSE and PROVENANCE.json."""

from __future__ import annotations
import hashlib
import struct
from pathlib import Path
from typing import Any
import zstandard as zstd
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .probe import (
    ARCHIVE_HEADER_SIZE,
    INNER_MAGIC,
    MEMBER_ENVELOPE_CIPHERTEXT_OFFSET,
    MEMBER_ENVELOPE_HEADER,
    MEMBER_ENVELOPE_IV_SIZE,
    MEMBER_ENVELOPE_KEY_SIZE,
    OUTER_MAGIC,
    ZSTD_MAGIC,
    validated_probe,
    decompress_bounded,
)
from .decode import TACTIC_MENTALITIES_ENUM, parse_tac_plaintext

DEFAULT_ZSTD_LEVEL = 3
TACTIC_NAME_LENGTH_OFFSET = 16


def _enum_label_to_cli_key(label: str) -> str:
    out: list[str] = []
    for index, char in enumerate(label):
        if char.isupper() and index and label[index - 1].islower():
            out.append("-")
        out.append(char.casefold())
    return "".join(out).replace("_", "-").replace(" ", "-")


MENTALITY_OPTION_VALUES = {
    _enum_label_to_cli_key(value): enum_id
    for enum_id, value in TACTIC_MENTALITIES_ENUM.items()
    if value != "None"
}
MENTALITY_VALUE_ALIASES = {
    alias: enum_id
    for enum_id, value in TACTIC_MENTALITIES_ENUM.items()
    if value != "None"
    for alias in {
        _enum_label_to_cli_key(value),
        value.casefold(),
        value.casefold().replace("_", "-").replace(" ", "-"),
    }
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_native_member(
    member_bytes: bytes, raw_size: int | None = None
) -> dict[str, Any]:
    """Decode one native member envelope into plaintext plus key/IV metadata."""
    if not member_bytes.startswith(MEMBER_ENVELOPE_HEADER):
        return {
            "status": "not_member_envelope",
            "plaintext": member_bytes,
            "key": None,
            "iv": None,
            "is_zstd": False,
        }
    if len(member_bytes) < MEMBER_ENVELOPE_CIPHERTEXT_OFFSET:
        raise ValueError("Member envelope is too short for key/IV/ciphertext.")
    key_start = len(MEMBER_ENVELOPE_HEADER)
    iv_start = key_start + MEMBER_ENVELOPE_KEY_SIZE
    ciphertext_start = iv_start + MEMBER_ENVELOPE_IV_SIZE
    key = member_bytes[key_start:iv_start]
    iv = member_bytes[iv_start:ciphertext_start]
    ciphertext = member_bytes[ciphertext_start:]
    decryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    aes_plain = decryptor.update(ciphertext) + decryptor.finalize()
    if raw_size is not None and not 0 <= raw_size <= 64 * 1024 * 1024:
        raise ValueError("Declared native member size exceeds the supported limit.")
    if aes_plain.startswith(ZSTD_MAGIC):
        plaintext = decompress_bounded(aes_plain, 64 * 1024 * 1024)
        return {
            "status": "aes_ctr_plus_zstd_decoded",
            "plaintext": plaintext,
            "key": key,
            "iv": iv,
            "is_zstd": True,
            "aes_plain_size": len(aes_plain),
        }
    return {
        "status": "aes_ctr_decoded",
        "plaintext": aes_plain,
        "key": key,
        "iv": iv,
        "is_zstd": False,
        "aes_plain_size": len(aes_plain),
    }


def encode_native_member(
    *,
    plaintext: bytes,
    key: bytes | None,
    iv: bytes | None,
    is_zstd: bool,
    zstd_level: int = DEFAULT_ZSTD_LEVEL,
) -> bytes:
    """Encode plaintext back into a native member envelope."""
    if key is None or iv is None:
        return plaintext
    if len(key) != MEMBER_ENVELOPE_KEY_SIZE:
        raise ValueError(f"Expected {MEMBER_ENVELOPE_KEY_SIZE}-byte AES key.")
    if len(iv) != MEMBER_ENVELOPE_IV_SIZE:
        raise ValueError(f"Expected {MEMBER_ENVELOPE_IV_SIZE}-byte AES CTR IV.")
    aes_input = (
        zstd.ZstdCompressor(level=zstd_level).compress(plaintext)
        if is_zstd
        else plaintext
    )
    encryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
    ciphertext = encryptor.update(aes_input) + encryptor.finalize()
    return MEMBER_ENVELOPE_HEADER + key + iv + ciphertext


def extract_member_plaintexts(path: str | Path) -> dict[str, bytes]:
    """Return decoded plaintext payloads keyed by member extension."""
    source = Path(path).expanduser()
    data = source.read_bytes()
    result = validated_probe(source)
    payloads: dict[str, bytes] = {}
    for member in result.get("members") or []:
        if member.get("layout_status") != "ok":
            continue
        extension = str(member.get("extension") or "")
        if not extension.startswith("."):
            continue
        start = int(member["offset"])
        end = start + int(member["stored_size"])
        decoded = decode_native_member(
            data[start:end], int(member.get("raw_size_from_toc") or 0) or None
        )
        plaintext = decoded.get("plaintext")
        if (
            not isinstance(plaintext, bytes)
            or len(plaintext) != member["raw_size_from_toc"]
        ):
            raise ValueError(
                "Native member decompressed size does not match its table record."
            )
        payloads[extension] = plaintext
    return payloads


def replace_tac_name(tac_plaintext: bytes, new_name: str) -> bytes:
    """Replace the length-prefixed tactic name in a decoded `.tac` payload."""
    if (
        len(tac_plaintext) < TACTIC_NAME_LENGTH_OFFSET + 4
        or tac_plaintext[2:6] != b"cat."
    ):
        raise ValueError(
            "Decoded .tac payload does not look like cat. tactic plaintext."
        )
    encoded = new_name.encode("utf-8")
    if not encoded:
        raise ValueError("Tactic name must not be empty.")
    if len(encoded) > 512:
        raise ValueError("Tactic name is too long.")
    old_length = int.from_bytes(
        tac_plaintext[TACTIC_NAME_LENGTH_OFFSET : TACTIC_NAME_LENGTH_OFFSET + 4],
        "little",
    )
    old_start = TACTIC_NAME_LENGTH_OFFSET + 4
    old_end = old_start + old_length
    if old_length <= 0 or old_end > len(tac_plaintext):
        raise ValueError("Existing .tac tactic name field is malformed.")
    return (
        tac_plaintext[:TACTIC_NAME_LENGTH_OFFSET]
        + len(encoded).to_bytes(4, "little")
        + encoded
        + tac_plaintext[old_end:]
    )


def replace_mentality(tac_plaintext: bytes, selected_label: str) -> bytes:
    """Replace the evidenced FM.UI.TacticMentalities byte in `.tac` bytes."""
    normalized = selected_label.strip().casefold().replace("_", "-").replace(" ", "-")
    if normalized not in MENTALITY_VALUE_ALIASES:
        allowed = ", ".join(sorted(MENTALITY_OPTION_VALUES))
        raise ValueError(
            f"Unsupported mentality {selected_label!r}; expected one of: {allowed}."
        )
    parsed = parse_tac_plaintext(tac_plaintext)
    setup = parsed.get("pre_style_setup") or {}
    offset = setup.get("mentality_offset")
    if not isinstance(offset, int) or not 0 <= offset < len(tac_plaintext):
        raise ValueError("Decoded .tac payload has no proven mentality byte.")
    data = bytearray(tac_plaintext)
    data[offset] = MENTALITY_VALUE_ALIASES[normalized]
    return bytes(data)


def repack_native_fmf(
    src_path: str | Path,
    out_path: str | Path,
    *,
    plaintext_overrides: dict[str, bytes] | None = None,
    zstd_level: int = DEFAULT_ZSTD_LEVEL,
) -> dict[str, Any]:
    """Rebuild a native SI `.fmf` archive with optional plaintext overrides."""
    source = Path(src_path).expanduser()
    output = Path(out_path).expanduser()
    plaintext_overrides = plaintext_overrides or {}
    data = source.read_bytes()
    if not data.startswith(OUTER_MAGIC):
        raise ValueError("Input is not a native SI afe. tactic archive.")
    result = validated_probe(source)
    zstd_toc_offset = result.get("zstd_toc_offset")
    if not isinstance(zstd_toc_offset, int) or zstd_toc_offset < 0:
        raise ValueError("Could not locate compressed native .fmf TOC.")
    toc_raw = decompress_bounded(data[zstd_toc_offset:], 2000000)
    new_toc = bytearray(toc_raw)
    encoded_members: list[dict[str, Any]] = []
    for member in result.get("members") or []:
        if member.get("layout_status") != "ok":
            continue
        extension = str(member.get("extension") or "")
        if not extension.startswith("."):
            continue
        start = int(member["offset"])
        stored_size = int(member["stored_size"])
        raw_size = int(member.get("raw_size_from_toc") or 0) or None
        decoded = decode_native_member(data[start : start + stored_size], raw_size)
        plaintext = decoded.get("plaintext")
        if not isinstance(plaintext, bytes):
            raise ValueError(f"Could not decode plaintext for member {extension}.")
        if extension in plaintext_overrides:
            plaintext = plaintext_overrides[extension]
        encoded = encode_native_member(
            plaintext=plaintext,
            key=decoded.get("key"),
            iv=decoded.get("iv"),
            is_zstd=bool(decoded.get("is_zstd")),
            zstd_level=zstd_level,
        )
        encoded_members.append(
            {
                "extension": extension,
                "original_logical_offset": int(member["logical_data_offset"]),
                "bytes": encoded,
                "raw_size": len(plaintext),
                "decode_status": decoded["status"],
            }
        )
    encoded_members.sort(key=lambda item: int(item["original_logical_offset"]))
    member_offsets: dict[str, tuple[int, int, int]] = {}
    member_data_parts: list[bytes] = []
    logical_offset = 0
    for item in encoded_members:
        encoded = item["bytes"]
        stored_size = len(encoded)
        member_offsets[item["extension"]] = (
            logical_offset,
            stored_size,
            int(item["raw_size"]),
        )
        member_data_parts.append(encoded)
        logical_offset += stored_size
    for record in (result.get("toc") or {}).get("extension_records") or []:
        extension = record.get("extension")
        if extension not in member_offsets:
            continue
        new_logical, new_stored, new_raw = member_offsets[extension]
        after_extension = (
            int(record["offset"]) + 4 + len(str(extension).encode("utf-8"))
        )
        struct.pack_into("<Q", new_toc, after_extension, new_logical)
        struct.pack_into("<Q", new_toc, after_extension + 8, new_stored)
        struct.pack_into("<Q", new_toc, after_extension + 16, new_raw)
    compressed_toc = zstd.ZstdCompressor(level=zstd_level).compress(bytes(new_toc))
    new_nested_offset = ARCHIVE_HEADER_SIZE + logical_offset
    new_outer_payload_len = new_nested_offset - 9
    if not 0 <= new_outer_payload_len <= 16777215:
        raise ValueError(
            "Repacked archive is too large for the observed u24 payload length field."
        )
    header = bytearray(data[:ARCHIVE_HEADER_SIZE])
    header[9] = new_outer_payload_len & 255
    header[10] = new_outer_payload_len >> 8 & 255
    header[11] = new_outer_payload_len >> 16 & 255
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        bytes(header) + b"".join(member_data_parts) + INNER_MAGIC + compressed_toc
    )
    return {
        "source": str(source),
        "output": str(output),
        "sourceSha256": file_sha256(source),
        "outputSha256": file_sha256(output),
        "sourceSize": len(data),
        "outputSize": output.stat().st_size,
        "originalNestedOffset": result.get("nested_fmf_offset"),
        "newNestedOffset": new_nested_offset,
        "originalOuterPayloadLength": result.get("outer_payload_len_u24_at_0x09"),
        "newOuterPayloadLength": new_outer_payload_len,
        "members": [
            {
                "extension": item["extension"],
                "logicalOffset": member_offsets[item["extension"]][0],
                "storedSize": member_offsets[item["extension"]][1],
                "rawSize": member_offsets[item["extension"]][2],
                "decodeStatus": item["decode_status"],
                "overridden": item["extension"] in plaintext_overrides,
            }
            for item in encoded_members
        ],
    }
