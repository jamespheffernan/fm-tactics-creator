import unittest
from unittest.mock import patch
from fm_tactics_creator.defensive_line import (
    DEFENSIVE_LINE_FLAGS, defensive_line_selection, replace_defensive_line, describe_defensive_line,
)


class DefensiveLineTests(unittest.TestCase):
    def parse(self):
        return patch("fm_tactics_creator.defensive_line.parse_tac_plaintext", return_value={
            "pre_style_setup": {"team_instruction_vector_candidate_offset": 4,
                                "team_instruction_vector_candidate_size": 12}})

    def test_every_transition_preserves_every_unrequested_bit(self):
        with self.parse():
            for before in DEFENSIVE_LINE_FLAGS.values():
                source = bytes(range(11)) + bytes([0xA0 | before]) + bytes(range(12, 24))
                for label, value in DEFENSIVE_LINE_FLAGS.items():
                    changed = replace_defensive_line(source, label)
                    self.assertEqual(defensive_line_selection(changed), (11, label))
                    self.assertEqual(changed[:11] + changed[12:], source[:11] + source[12:])
                    self.assertEqual(changed[11] & 0xF0, 0xA0)
                    self.assertEqual(changed[11] & 15, value)

    def test_contradictory_and_unknown_selection_rejected(self):
        with self.parse():
            for value in range(16):
                if value in DEFENSIVE_LINE_FLAGS.values():
                    continue
                with self.assertRaisesRegex(ValueError, "contradictory"):
                    replace_defensive_line(bytes(11) + bytes([value]) + bytes(12), "Higher Defensive Line")
            with self.assertRaisesRegex(ValueError, "Unsupported stored"):
                replace_defensive_line(bytes(24), "Standard")

    def test_conflicting_inherited_choices_are_reported_without_guessing(self):
        with self.parse():
            self.assertEqual(describe_defensive_line(bytes(11) + b"\x03" + bytes(12)), {"defensive_line": None, "defensive_line_state": "conflicting_stored_selections"})

    def test_vector_bounds_fail_closed(self):
        with self.parse():
            with self.assertRaisesRegex(ValueError, "vector"):
                defensive_line_selection(bytes(15))
