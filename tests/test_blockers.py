"""Offline checks for the per-target install blockers data export."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_blockers


class BlockersTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.coverage = self.root / "coverage.json"
        self.out = self.root / "data" / "blockers.json"
        self.scan = {
            "schema": 1,
            "generated": "2026-11-17T00:00:00+00:00",
            "targets": [{"label": "3.14 win-arm64"}, {"label": "3.14 linux-x86_64"}],
            "packages": [
                {
                    "rank": 1,
                    "name": "app1",
                    "version": "1.0",
                    "install": {
                        "3.14 win-arm64": {
                            "status": "source",
                            "blockers": [
                                {"name": "cryptography", "version": "42.0", "status": "source", "via": ["app1", "cryptography"]},
                                {"name": "cffi", "version": "1.17", "status": "source", "via": ["app1", "cryptography", "cffi"]},
                            ],
                        },
                        "3.14 linux-x86_64": {
                            "status": "wheel",
                            "blockers": [],
                        },
                    },
                },
                {
                    "rank": 2,
                    "name": "app2",
                    "version": "2.0",
                    "install": {
                        "3.14 win-arm64": {
                            "status": "source",
                            "blockers": [
                                # Repeated blocker in the same tree (via two routes) must only count once
                                {"name": "cryptography", "version": "42.0", "status": "source", "via": ["app2", "cryptography"]},
                                {"name": "cryptography", "version": "42.0", "status": "source", "via": ["app2", "jwt", "cryptography"]},
                            ],
                        },
                        "3.14 linux-x86_64": {
                            "status": "not_checked",
                            "blockers": [
                                {"name": "cryptography", "version": "42.0", "status": "source", "via": ["cryptography"]},
                            ],
                        },
                    },
                },
                {
                    "rank": 3,
                    "name": "app3",
                    "version": "3.0",
                    "install": {
                        "3.14 win-arm64": {
                            "status": "not_checked",
                            "blockers": [
                                {"name": "cryptography", "version": "42.0", "status": "source", "via": ["cryptography"]},
                            ],
                        },
                    },
                },
            ],
        }

    def write_scan(self):
        self.coverage.write_text(json.dumps(self.scan), encoding="utf-8")

    def test_counts_and_ranks_blockers(self):
        self.write_scan()
        count = build_blockers.build(self.coverage, self.out)
        self.assertEqual(count, 2)
        report = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(report["generated"], self.scan["generated"])

        win = report["targets"]["3.14 win-arm64"]
        self.assertEqual(win["checked"], 2)  # app1 and app2 (app3 is not_checked)
        self.assertEqual(len(win["blockers"]), 2)

        # cryptography blocks app1 and app2 (duplicate in app2 counted only once)
        b0 = win["blockers"][0]
        self.assertEqual(b0["name"], "cryptography")
        self.assertEqual(b0["count"], 2)
        self.assertEqual(b0["examples"], ["app1", "app2"])

        # cffi blocks app1
        b1 = win["blockers"][1]
        self.assertEqual(b1["name"], "cffi")
        self.assertEqual(b1["count"], 1)
        self.assertEqual(b1["examples"], ["app1"])

        # linux target: 1 checked (app1), app2 was not_checked
        lin = report["targets"]["3.14 linux-x86_64"]
        self.assertEqual(lin["checked"], 1)
        self.assertEqual(lin["blockers"], [])

    def test_caps_each_target_at_fifty(self):
        # Create 60 distinct blockers for target
        blockers = [{"name": f"dep-{i}", "status": "source"} for i in range(60)]
        self.scan["packages"] = [{
            "rank": 1,
            "name": "big-app",
            "install": {
                "3.14 win-arm64": {"status": "source", "blockers": blockers},
            },
        }]
        self.write_scan()
        build_blockers.build(self.coverage, self.out)
        report = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(len(report["targets"]["3.14 win-arm64"]["blockers"]), 50)

    def test_skips_unsafe_blocker_names(self):
        self.scan["packages"] = [{
            "rank": 1,
            "name": "app",
            "install": {
                "3.14 win-arm64": {
                    "status": "source",
                    "blockers": [
                        {"name": "<script>alert(1)</script>", "status": "source"},
                        {"name": "../evil", "status": "source"},
                        {"name": "valid-name", "status": "source"},
                    ],
                },
            },
        }]
        self.write_scan()
        build_blockers.build(self.coverage, self.out)
        report = json.loads(self.out.read_text(encoding="utf-8"))
        blockers = report["targets"]["3.14 win-arm64"]["blockers"]
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["name"], "valid-name")

    def test_rejects_unknown_scan_schema(self):
        self.scan["schema"] = 2
        self.write_scan()
        with self.assertRaisesRegex(SystemExit, "schema 2.*expected 1"):
            build_blockers.build(self.coverage, self.out)
        self.assertFalse(self.out.exists())

    def test_cli_execution(self):
        self.write_scan()
        result = subprocess.run(
            [sys.executable, str(Path(build_blockers.__file__)), str(self.coverage), str(self.out)],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("blockers: 2 entries", result.stdout)


if __name__ == "__main__":
    unittest.main()
