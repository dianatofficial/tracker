"""Offline regression tests for the daily wheel-change history (issue #116)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts import update_changes

TODAY = "2026-11-17"
LINUX = {"label": "3.14 linux-x86_64", "python": "3.14", "platform": "linux-x86_64"}
WINDOWS = {"label": "3.14 win-arm64", "python": "3.14", "platform": "win-arm64"}


def package(name: str, *statuses: str) -> dict:
    return {"name": name, "version": "1.0", "results": list(statuses)}


def scan(packages: list[dict], targets: list[dict] | None = None, *, day: str = TODAY) -> dict:
    return {
        "wheelgap": "0.13.0",
        "generated": day + "T10:00:00+00:00",
        "targets": targets if targets is not None else [LINUX],
        "packages": packages,
    }


class UpdateChangesRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.previous = self.root / "previous.json"
        self.coverage = self.root / "coverage.json"
        self.changes = self.root / "changes.json"

    def record(self, before: dict | None, after: dict) -> tuple[dict | str, list[dict]]:
        if before is None:
            self.previous.unlink(missing_ok=True)
        else:
            self.previous.write_text(json.dumps(before), encoding="utf-8")
        self.coverage.write_text(json.dumps(after), encoding="utf-8")
        entry = update_changes.update(self.previous, self.coverage, self.changes)
        history = json.loads(self.changes.read_text(encoding="utf-8"))
        return entry, history

    def test_90_day_cutoff_retains_exactly_the_last_90_calendar_days(self) -> None:
        today = date.fromisoformat(TODAY)
        old_date = (today - timedelta(days=90)).isoformat()
        boundary = (today - timedelta(days=89)).isoformat()
        self.changes.write_text(
            json.dumps([
                {"date": old_date, "gained": [], "lost": []},
                {"date": boundary, "gained": [], "lost": []},
            ]),
            encoding="utf-8",
        )
        _, history = self.record(scan([package("a", "wheel")]), scan([package("a", "source")]))
        self.assertEqual([entry["date"] for entry in history], [boundary, TODAY])
        self.assertEqual(history[-1]["lost"][0]["name"], "a")

    def test_same_day_loss_then_regain_disappears(self) -> None:
        # b's loss isn't reversed, so it must survive the merge: only a's round trip cancels out.
        first = scan([package("a", "wheel"), package("b", "wheel")])
        second = scan([package("a", "source"), package("b", "source")])
        third = scan([package("a", "wheel"), package("b", "source")])
        first_entry, _ = self.record(first, second)
        self.assertEqual(len(first_entry["lost"]), 2)
        latest, history = self.record(second, third)
        b_lost = {"name": "b", "version": "1.0", "target": "3.14 linux-x86_64", "from": "wheel", "to": "source"}
        self.assertEqual(latest, {"date": TODAY, "gained": [], "lost": [b_lost]})
        self.assertEqual(history, [latest])

    def test_same_day_regain_then_loss_disappears(self) -> None:
        first = scan([package("a", "source")])
        second = scan([package("a", "wheel")])
        third = scan([package("a", "source")])
        self.record(first, second)
        latest, history = self.record(second, third)
        self.assertEqual(latest, {"date": TODAY, "gained": [], "lost": []})
        self.assertEqual(history, [latest])

    def test_unknown_cells_never_count_as_a_gain_or_loss(self) -> None:
        for before, after in (("unknown", "wheel"), ("wheel", "unknown")):
            with self.subTest(before=before, after=after):
                self.assertEqual(
                    update_changes.diff(scan([package("a", before)]), scan([package("a", after)])),
                    ([], []),
                )

    def test_a_new_target_does_not_create_spurious_gains(self) -> None:
        # The new target comes first, so matching targets by position would misfire.
        old = scan([package("a", "wheel")])
        new = scan([package("a", "wheel", "source")], [WINDOWS, LINUX])
        gained, lost = update_changes.diff(old, new)
        self.assertEqual(gained, [])
        self.assertEqual([(i["target"], i["from"], i["to"]) for i in lost],
                         [("3.14 linux-x86_64", "wheel", "source")])

    def test_a_removed_target_does_not_create_spurious_losses(self) -> None:
        # Different statuses per target, so matching targets by position would find no loss.
        old = scan([package("a", "source", "wheel")], [WINDOWS, LINUX])
        new = scan([package("a", "source")])
        gained, lost = update_changes.diff(old, new)
        self.assertEqual(gained, [])
        self.assertEqual([(i["target"], i["from"], i["to"]) for i in lost],
                         [("3.14 linux-x86_64", "wheel", "source")])

    def test_packages_added_or_removed_from_the_ranked_scan_are_skipped(self) -> None:
        old = scan([package("gone", "wheel"), package("common", "wheel")])
        new = scan([package("common", "source"), package("added", "wheel")])
        gained, lost = update_changes.diff(old, new)
        self.assertEqual(gained, [])
        self.assertEqual([item["name"] for item in lost], ["common"])

    def test_no_previous_scan_reports_reason_and_preserves_history(self) -> None:
        existing = [{"date": "2026-11-16", "gained": [], "lost": []}]
        self.changes.write_text(json.dumps(existing), encoding="utf-8")
        entry, history = self.record(None, scan([package("a", "wheel")]))
        self.assertIn("nothing to compare", entry)
        self.assertEqual(history, existing)

    def test_missing_change_history_is_initialised(self) -> None:
        entry, history = self.record(scan([package("a", "source")]), scan([package("a", "wheel")]))
        self.assertEqual(history, [entry])
        self.assertEqual(len(entry["gained"]), 1)
        self.assertEqual(entry["lost"], [])


if __name__ == "__main__":
    unittest.main()
