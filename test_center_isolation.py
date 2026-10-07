"""Complaint reports must not cross regions when source data has a bad REGION label."""
import unittest
from unittest.mock import patch

import pandas as pd

import data_processor as processor


class ComplaintCenterIsolationTests(unittest.TestCase):
    def setUp(self):
        self.centers = [{
            "center_name": "Manarkad",
            "adl_area_key": "Manarkad",
            "adtv_amo_key": "Manarkad",
            "prepaid_area_key": "Manarkad",
        }]

    @patch.object(processor.db_manager, "get_centers")
    def test_similar_center_names_remain_region_isolated(self, get_centers):
        get_centers.return_value = self.centers
        adl = pd.DataFrame({
            "REGION": ["Thrissur", "Thrissur"],
            "AREA": ["Manarkad", "Manarkadu"],
            "COMPLAINTTYPE": [processor.ADL_COMPLAINT_TYPE] * 2,
            "PROBLEMTYPE": [processor.ADL_PROBLEM_TYPES[0]] * 2,
        })
        adtv = pd.DataFrame({
            "REGION": ["Thrissur", "Thrissur"],
            "SERVICEAMO": ["Manarkad", "Manarkadu"],
            "COMPLAINTTYPE": [processor.ADTV_COMPLAINT_TYPE] * 2,
        })
        prepaid = pd.DataFrame({
            "REGION": ["Thrissur", "Thrissur"],
            "Area": ["Manarkad", "Manarkadu"],
            "Complaint": [processor.PREPAID_COMPLAINT_TYPE] * 2,
        })

        self.assertEqual(processor.filter_adl(adl, "thrissur")["AREA"].tolist(), ["Manarkad"])
        self.assertEqual(processor.filter_adtv(adtv, "thrissur")["SERVICEAMO"].tolist(), ["Manarkad"])
        self.assertEqual(processor.filter_prepaid(prepaid, "thrissur")["Area"].tolist(), ["Manarkad"])

    @patch.object(processor.db_manager, "get_centers")
    def test_complaint_filters_are_exact_with_portal_style_headers(self, get_centers):
        get_centers.return_value = self.centers
        adl = pd.DataFrame({
            "Region": ["Thrissur"] * 3,
            "Area": ["Manarkad"] * 3,
            "ComplaintType": ["Network", "Network", "Billing"],
            "ProblemType": ["Network Complaints", "Onsite Visit", "Network Complaint Extra"],
        })
        adtv = pd.DataFrame({
            "Region": ["Thrissur", "Thrissur"],
            "ServiceAMO": ["Manarkad", "Manarkad"],
            "ComplaintType": ["Network", "Billing"],
        })
        prepaid = pd.DataFrame({
            "Area": ["Manarkad", "Manarkad"],
            "Complaint Type": ["Network", "Network Support"],
        })

        self.assertEqual(len(processor.filter_adl(adl, "thrissur")), 2)
        self.assertEqual(len(processor.filter_adtv(adtv, "thrissur")), 1)
        self.assertEqual(len(processor.filter_prepaid(prepaid, "thrissur")), 1)


if __name__ == "__main__":
    unittest.main()
