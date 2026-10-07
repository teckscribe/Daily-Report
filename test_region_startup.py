"""Regression checks using a temporary database, never the installation's data."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


class RegionStartupTests(unittest.TestCase):
    def test_deleted_thrissur_stays_deleted_after_restart_and_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ModuleType("config")
            config.DATA_DIR = Path(directory)
            config.DEFAULT_REGION_ID = "kottayam"
            config.DEFAULT_REGION_NAME = "Kottayam"
            config.TARGET_REGION = "Kottayam CRM"
            config.PREPAID_REGION = "Kottayam Prepaid"
            spec = importlib.util.spec_from_file_location(
                "isolated_region_db", Path(__file__).with_name("db_manager.py")
            )
            db = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {"config": config}):
                spec.loader.exec_module(db)
            self.assertEqual([r["id"] for r in db.get_all_regions()], ["kottayam"])
            configured = db.get_region_by_id("kottayam")
            self.assertEqual(configured["softcode_region"], "Kottayam CRM")
            self.assertEqual(configured["prepaid_region"], "Kottayam Prepaid")
            db.add_region("thrissur", "Thrissur", "Thrissur", "Thrissur")
            db.delete_region("thrissur")
            # A leftover roster used to bring the deleted region back on access.
            (Path(directory) / "employee_directory.json").write_text(
                '[{"name": "Old roster"}]', encoding="utf-8"
            )
            for _ in range(2):
                db.init_db()
                self.assertFalse(db.auto_sync_directory_from_disk("thrissur"))
                self.assertIsNone(db.get_region_by_id("thrissur"))
                self.assertIsNotNone(db.get_region_by_id("kottayam"))


if __name__ == "__main__":
    unittest.main()
