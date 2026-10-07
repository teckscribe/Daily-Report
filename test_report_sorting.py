"""Rendered report rows must always be ordered by displayed center name."""
import unittest

from report_engine import ReportRow, _alphabetical_rows


class ReportSortingTests(unittest.TestCase):
    def test_centers_sort_case_insensitively_then_by_staff_name(self):
        rows = [
            ReportRow("Vaikom", "Zed", 0, []),
            ReportRow("Kottayam", "Bravo", 0, []),
            ReportRow("Kottayam", "Alice", 0, []),
            ReportRow("changancherry", "Chris", 0, []),
        ]
        ordered = _alphabetical_rows(rows)
        self.assertEqual(
            [(row.center, row.name) for row in ordered],
            [
                ("changancherry", "Chris"),
                ("Kottayam", "Alice"),
                ("Kottayam", "Bravo"),
                ("Vaikom", "Zed"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
