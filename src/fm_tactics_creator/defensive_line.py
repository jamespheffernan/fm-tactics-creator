"""Stored defensive-line selection; no claim about effective/default height."""
from ._codec.decode import parse_tac_plaintext

DEFENSIVE_LINE_FLAGS = {
    "No explicit selection": 0,
    "Much Higher Defensive Line": 1,
    "Higher Defensive Line": 2,
    "Lower Defensive Line": 4,
    "Much Lower Defensive Line": 8,
}


def defensive_line_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get("pre_style_setup", {})
    offset = setup.get("team_instruction_vector_candidate_offset")
    if (not isinstance(offset, int) or offset < 0
            or setup.get("team_instruction_vector_candidate_size") != 12
            or offset + 12 > len(tac)):
        raise ValueError("Unsupported native team instruction vector.")
    value = tac[offset + 7] & 15
    names = {value: name for name, value in DEFENSIVE_LINE_FLAGS.items()}
    if value not in names:
        raise ValueError("Template has contradictory stored defensive-line selections.")
    return offset + 7, names[value]


def replace_defensive_line(tac: bytes, label: str) -> bytes:
    if label not in DEFENSIVE_LINE_FLAGS:
        raise ValueError("Unsupported stored defensive-line selection.")
    offset, _ = defensive_line_selection(tac)
    result = bytearray(tac)
    result[offset] = (result[offset] & 0xF0) | DEFENSIVE_LINE_FLAGS[label]
    return bytes(result)


def describe_defensive_line(tac: bytes) -> dict:
    """Report ambiguous stored choices without blocking unrelated inherited edits."""
    try:
        _, label = defensive_line_selection(tac)
    except ValueError as error:
        if str(error) != "Template has contradictory stored defensive-line selections.":
            raise
        return {"defensive_line": None, "defensive_line_state": "conflicting_stored_selections"}
    return {"defensive_line": label, "defensive_line_state": "known"}
