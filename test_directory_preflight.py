"""Employee Directory must agree with report layout before reports can render."""
import unittest
from unittest.mock import patch

import db_manager


class DirectoryPreflightTests(unittest.TestCase):
    def setUp(self):
        self.center = {"center_name": "Kottayam"}
        self.tl = {
            "name": "Jitto George",
            "center_name": "Kottayam",
            "pd_adl_name_key": "Jitto George",
            "pd_adtv_name_key": "Jitto George",
            "pp_adl_emp_code": "1607",
            "pp_adtv_emp_code": "1607",
        }
        self.acso = {
            "acso_name": "Jobin Chacko",
            "center_name": "Kottayam",
            "emp_code": "2428",
            "pd_adl_center_key": "Kottayam",
            "pd_adtv_center_key": "KOTTAYAM (DA01)",
            "pp_adl_center_key": "KOTTAYAM",
            "pp_adtv_center_key": "KOTTAYAM",
        }
        self.employees = [
            {"name": "Jitto George", "role": "Team Leader", "center_name": "Kottayam", "emp_code": "1607"},
            {"name": "Jobin Chacko", "role": "ACSO", "center_name": "Kottayam", "emp_code": "2428"},
        ]

    @patch.object(db_manager, "get_employees")
    @patch.object(db_manager, "get_acsos")
    @patch.object(db_manager, "get_team_leaders")
    @patch.object(db_manager, "get_centers")
    def test_matching_directory_passes(self, get_centers, get_team_leaders, get_acsos, get_employees):
        get_centers.return_value = [self.center]
        get_team_leaders.return_value = [self.tl]
        get_acsos.return_value = [self.acso]
        get_employees.return_value = self.employees
        self.assertEqual(db_manager.validate_region_report_directory("kottayam"), [])

    @patch.object(db_manager, "get_employees")
    @patch.object(db_manager, "get_acsos")
    @patch.object(db_manager, "get_team_leaders")
    @patch.object(db_manager, "get_centers")
    def test_missing_or_mismatched_staff_is_reported(self, get_centers, get_team_leaders, get_acsos, get_employees):
        get_centers.return_value = [self.center]
        get_team_leaders.return_value = [self.tl]
        get_acsos.return_value = [self.acso]
        get_employees.return_value = [{"name": "Wrong Name", "role": "Team Leader", "center_name": "Kottayam", "emp_code": "1607"}]
        issues = db_manager.validate_region_report_directory("kottayam")
        self.assertTrue(any("Jitto George" in issue for issue in issues))
        self.assertTrue(any("Jobin Chacko" in issue for issue in issues))

    @patch.object(db_manager, "get_employees")
    @patch.object(db_manager, "get_acsos")
    @patch.object(db_manager, "get_team_leaders")
    @patch.object(db_manager, "get_centers")
    def test_missing_crm_lookup_key_is_reported(self, get_centers, get_team_leaders, get_acsos, get_employees):
        incomplete_tl = {**self.tl, "pd_adtv_name_key": ""}
        get_centers.return_value = [self.center]
        get_team_leaders.return_value = [incomplete_tl]
        get_acsos.return_value = [self.acso]
        get_employees.return_value = self.employees
        issues = db_manager.validate_region_report_directory("kottayam")
        self.assertTrue(any("pd_adtv_name_key" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
