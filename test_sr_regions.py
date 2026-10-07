"""Service Request region isolation without touching the installation database."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import pandas as pd


class ServiceRequestRegionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "isolated_sr", Path(__file__).with_name("service_request_engine.py")
        )
        self.sr = importlib.util.module_from_spec(spec)
        db = ModuleType("db_manager")
        db.get_region_by_id = Mock(return_value={"softcode_region": "Kottayam", "prepaid_region": "Kottayam"})
        db.get_all_regions = Mock(return_value=[{"id": "kottayam"}])
        db.get_centers = Mock(return_value=[{
            "center_name": "Kottayam",
            "adl_area_key": "Kottayam",
            "adtv_amo_key": "Kottayam",
            "prepaid_area_key": "Kottayam",
        }])
        self.db = db
        with patch.dict(sys.modules, {"db_manager": db}):
            spec.loader.exec_module(self.sr)

    def test_region_paths_are_separate_and_reject_traversal(self):
        self.assertNotEqual(self.sr.sr_output_path("a.jpg", "kottayam"), self.sr.sr_output_path("a.jpg", "thrissur"))
        with self.assertRaises(ValueError):
            self.sr.sr_output_path("a.jpg", "../thrissur")

    def test_mixed_workbook_filters_all_sheets_and_allows_single_region_exports(self):
        adl = pd.DataFrame({
            "REGION": ["Kottayam", "Kottayam", "Thrissur"],
            "AREA": ["Kottayam", "Manarkadu", "Chalakudy"],
            "PROBLEMSUBTYPE": ["Shifting Request"] * 3,
            "DAYSELAPSED": [2, 2, 2],
        })
        tv = adl.rename(columns={"AREA": "SERVICEAMO", "PROBLEMSUBTYPE": "PROBLEMTYPE"})
        prepaid = adl.rename(columns={"AREA": "Area", "PROBLEMSUBTYPE": "Complaint", "DAYSELAPSED": "TAT"})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xlsx"
            for missing in (False, True):
                with pd.ExcelWriter(source) as writer:
                    adl.to_excel(writer, sheet_name="ADL", index=False)
                    tv.to_excel(writer, sheet_name="ADTv", index=False)
                    (prepaid.drop(columns="REGION") if missing else prepaid).to_excel(writer, sheet_name="Prepaid", index=False)
                if missing:
                    sections = self.sr.compute_service_request_reports(source, "kottayam")
                    for frame in sections.values():
                        self.assertIsInstance(frame, pd.DataFrame)
                        self.assertNotIn("Chalakudy", frame.to_string())
                        self.assertNotIn("Manarkadu", frame.to_string())
                        self.assertIn("Kottayam", frame.to_string())
                else:
                    sections = self.sr.compute_service_request_reports(source, "kottayam")
                    for frame in sections.values():
                        self.assertNotIn("Chalakudy", frame.to_string())
                        self.assertNotIn("Manarkadu", frame.to_string())
                        self.assertIn("Kottayam", frame.to_string())
                    with patch.object(self.sr, "OUTPUT_DIR", Path(directory)):
                        excel = self.sr.create_excel_output(sections, region_id="kottayam")
                        self.assertEqual(excel.parent.name, "kottayam")
                        self.assertTrue(excel.exists())

    def test_unlabelled_export_is_rejected_when_multiple_regions_exist(self):
        self.db.get_all_regions.return_value = [{"id": "kottayam"}, {"id": "another-region"}]
        adl = pd.DataFrame({"AREA": ["Kottayam"], "PROBLEMSUBTYPE": ["Shifting Request"], "DAYSELAPSED": [2]})
        tv = adl.rename(columns={"AREA": "SERVICEAMO", "PROBLEMSUBTYPE": "PROBLEMTYPE"})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xlsx"
            with pd.ExcelWriter(source) as writer:
                adl.to_excel(writer, sheet_name="ADL", index=False)
                tv.to_excel(writer, sheet_name="ADTv", index=False)
            with self.assertRaisesRegex(ValueError, "no REGION column"):
                self.sr.compute_service_request_reports(source, "kottayam")

    def test_shared_service_names_and_prepaid_service_request_filter(self):
        adl = pd.DataFrame({
            "REGION": ["Kottayam"] * 3,
            "AREA": ["Kottayam"] * 3,
            "PROBLEMSUBTYPE": [
                "Shifting Request",
                "Cable Rerouting Required",
                "Reconnection - Cabling to be done",
            ],
            "DAYSELAPSED": [1, 2, 3],
        })
        tv = pd.DataFrame({
            "REGION": ["Kottayam"] * 3,
            "SERVICEAMO": ["Kottayam"] * 3,
            "PROBLEMTYPE": [
                "Shift Newconnection",
                "Cable Re-routing",
                "Reconnection req with field visit",
            ],
            "DAYSELAPSED": [1, 2, 3],
        })
        prepaid = pd.DataFrame({
            "REGION": ["Kottayam"] * 3,
            "Area": ["Kottayam"] * 3,
            "Complaint Type": ["Service Request", "Service Request", "Network"],
            "Complaint": ["Transfer to a New location", "Cable Rerouting Required", "Transfer to a New location"],
            "TAT": [1, 2, 3],
        })
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xlsx"
            with pd.ExcelWriter(source) as writer:
                adl.to_excel(writer, sheet_name="ADL", index=False)
                tv.to_excel(writer, sheet_name="ADTv", index=False)
                prepaid.to_excel(writer, sheet_name="Prepaid", index=False)
            sections = self.sr.compute_service_request_reports(source, "kottayam")
        adl_labels = set(sections["ADL Service Request Pending"]["Service Request Type"])
        adtv_labels = set(sections["ADTv Service Request Pending"]["Service Request Type"])
        self.assertEqual(adl_labels, {"Shifting", "Cable Rerouting", "Reconnection"})
        self.assertEqual(adtv_labels, {"Shifting", "Cable Rerouting", "Reconnection"})

    def test_service_request_centers_sort_case_insensitively(self):
        source = pd.DataFrame({
            "CENTER": ["Vaikom", "changancherry", "Kottayam"],
            "Service Request Type": ["Shifting", "Cable Rerouting", "Reconnection"],
            "Days": [1, 1, 1],
            "Pending Bucket": ["1 day", "1 day", "1 day"],
        })
        report = self.sr.build_pending_report(source)
        self.assertEqual(report["CENTER"].tolist(), ["changancherry", "Kottayam", "Vaikom"])

    def test_renderer_writes_only_selected_region(self):
        from PIL import Image
        browser = Mock()
        page = browser.new_context.return_value.new_page.return_value
        page.locator.return_value.screenshot.side_effect = lambda **kw: Image.new("RGB", (10, 10)).save(kw["path"])
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        manager = Mock()
        manager.__enter__ = Mock(return_value=playwright)
        manager.__exit__ = Mock(return_value=False)
        sections = {"ADL Service Request Pending": pd.DataFrame(), "ADTv Service Request Pending": pd.DataFrame()}
        with tempfile.TemporaryDirectory() as directory, patch.object(self.sr, "OUTPUT_DIR", Path(directory)), patch.object(self.sr, "sync_playwright", return_value=manager), patch.object(self.sr, "generate_sr_table_html", return_value="<table></table>"):
            paths = self.sr.render_sr_report_images(sections, region_id="kottayam")
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(p.exists() and p.parent.name == "kottayam" for p in paths))
            self.assertFalse((Path(directory) / "Daily_SR_Report_latest.jpg").exists())


if __name__ == "__main__":
    unittest.main()
