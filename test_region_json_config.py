"""Regression tests for installation-specific region.json loading."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RegionJsonConfigTests(unittest.TestCase):
    def test_json_overrides_conflicting_legacy_environment_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "region.json"
            config_path.write_text(json.dumps({
                "region_id": "kottayam",
                "region_name": "Kottayam",
                "softcode_region": "Kottayam CRM",
                "prepaid_region": "Kottayam Prepaid",
            }), encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "REGION_CONFIG_PATH": str(config_path),
                "DEFAULT_REGION_ID": "thrissur",
                "TARGET_REGION": "Thrissur",
                "PREPAID_REGION": "Thrissur",
            })
            result = subprocess.run(
                [sys.executable, "-c", "import config; print(config.DEFAULT_REGION_ID, config.TARGET_REGION, config.PREPAID_REGION)"],
                cwd=Path(__file__).parent,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), "kottayam Kottayam CRM Kottayam Prepaid")


if __name__ == "__main__":
    unittest.main()
