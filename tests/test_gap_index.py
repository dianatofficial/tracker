import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import build_gap_index

SHA = "c" * 64


def wheel(name="tiktoken", file="tiktoken-0.14.0-cp314-cp314-win_arm64.whl", **over):
    w = {"name": name, "version": "0.14.0", "target": "3.14 win-arm64", "wheel": file, "sha256": SHA,
         "requires_python": ">=3.9", "verified": "2026-11-16"}  # fmt: skip
    w.update(over)
    return w


class Index(unittest.TestCase):
    def build(self, wheels):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gap-wheels.json").write_text(json.dumps({"schema": 1, "wheels": wheels}))
        self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site"), 0)
        return tmp / "site"

    def test_pep_503_pages_link_the_wheels_repo_release(self):
        site = self.build([wheel(), wheel(name="Zope.Interface", file="zope_interface-8.7-cp314-cp314-win_arm64.whl")])
        root = (site / "wheels/simple/index.html").read_text()
        self.assertIn('<a href="tiktoken/">tiktoken</a>', root)
        self.assertIn('<a href="zope-interface/">zope-interface</a>', root)  # normalised as PEP 503 says
        page = (site / "wheels/simple/tiktoken/index.html").read_text()
        self.assertIn(
            '<a href="https://github.com/wheelgap/wheels/releases/download/gap-wheels/'
            f'tiktoken-0.14.0-cp314-cp314-win_arm64.whl#sha256={SHA}" data-requires-python="&gt;=3.9">',
            page,
        )
        self.assertNotIn("wheelgap/tracker/releases", page)
        record = json.loads((site / "data/gap-wheels.json").read_text())
        self.assertEqual(len(record["wheels"]), 2)  # the transparency record keeps its old address
        self.assertIn('name="pypi:repository-version"', page)

    def test_entries_that_cant_be_linked_safely_are_left_out(self):
        site = self.build([wheel(file="x.whl\"><script>"), wheel(sha256="nothex"), wheel(name="../evil")])
        self.assertEqual(list((site / "wheels/simple").iterdir()), [site / "wheels/simple/index.html"])

    def test_requires_python_is_escaped(self):
        site = self.build([wheel(requires_python='"><x')])
        project = (site / "wheels/simple/tiktoken/index.html").read_text()
        self.assertIn('data-requires-python="&quot;&gt;&lt;x"', project)

    def test_the_page_says_where_the_wheels_went(self):
        page = (self.build([wheel()]) / "wheels/index.html").read_text()
        self.assertIn('<link rel="canonical" href="https://wheelgap.github.io/wheels/">', page)
        self.assertIn("--extra-index-url https://wheelgap.github.io/wheels/simple/", page)
        self.assertNotIn("<table", page)

    def test_no_file_writes_only_the_moved_page(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertEqual(build_gap_index.build(tmp / "missing.json", tmp / "site"), 1)
        self.assertIn("Gap wheels have moved", (tmp / "site/wheels/index.html").read_text())
        self.assertFalse((tmp / "site/wheels/simple").exists())

    def test_malformed_file_writes_only_the_moved_page(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gap-wheels.json").write_text("{not json")
        self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site"), 1)
        self.assertFalse((tmp / "site/wheels/simple").exists())

    def test_no_wheels_list_writes_only_the_moved_page(self):
        for body in ('{"schema": 1}', '{"wheels": {}}', "[]"):
            tmp = Path(tempfile.mkdtemp())
            (tmp / "gap-wheels.json").write_text(body)
            self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site"), 1, body)
            self.assertFalse((tmp / "site/wheels/simple").exists())
            self.assertFalse((tmp / "site/data/gap-wheels.json").exists())

    def test_status_filters_withdrawn_wheels_and_keeps_in_index_and_yanked(self):
        tmp = Path(tempfile.mkdtemp())
        wheels = [
            wheel(name="tiktoken", file="tiktoken-0.14.0-cp314-cp314-win_arm64.whl"),
            wheel(name="tiktoken", file="tiktoken-0.13.0-cp314-cp314-win_arm64.whl"),
            wheel(name="tiktoken", file="tiktoken-0.12.0-cp314-cp314-win_arm64.whl"),
            wheel(name="gonepkg", file="gonepkg-1.0.0-cp314-cp314-win_arm64.whl"),
        ]
        status = {
            "schema": 1,
            "wheels": [
                {"project": "tiktoken", "wheel": "tiktoken-0.14.0-cp314-cp314-win_arm64.whl", "status": "in-index"},
                {"project": "tiktoken", "wheel": "tiktoken-0.13.0-cp314-cp314-win_arm64.whl", "status": "yanked", "yank_reason": "broken <build>"},
                {"project": "tiktoken", "wheel": "tiktoken-0.12.0-cp314-cp314-win_arm64.whl", "status": "withdrawn-pypi-has-wheel"},
                {"project": "gonepkg", "wheel": "gonepkg-1.0.0-cp314-cp314-win_arm64.whl", "status": "withdrawn-pypi-has-wheel"},
            ],
        }
        (tmp / "gap-wheels.json").write_text(json.dumps({"schema": 1, "wheels": wheels}))
        (tmp / "status.json").write_text(json.dumps(status))
        self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site", tmp / "status.json"), 0)

        root = (tmp / "site/wheels/simple/index.html").read_text()
        self.assertIn('<a href="tiktoken/">tiktoken</a>', root)
        self.assertNotIn("gonepkg", root)
        self.assertFalse((tmp / "site/wheels/simple/gonepkg").exists())

        page = (tmp / "site/wheels/simple/tiktoken/index.html").read_text()
        self.assertIn("tiktoken-0.14.0-cp314-cp314-win_arm64.whl", page)
        self.assertIn("tiktoken-0.13.0-cp314-cp314-win_arm64.whl", page)
        self.assertNotIn("tiktoken-0.12.0-cp314-cp314-win_arm64.whl", page)
        # A yanked wheel is marked as wheelgap/wheels' own index marks it (PEP 592), so pip skips it there too unless
        # a requirement pins that exact version; an in-index one isn't.
        links = {re.search(r">([^<>]+\.whl)</a>", line).group(1): line for line in page.splitlines() if "<a href=" in line}
        self.assertIn(' data-yanked="broken &lt;build&gt;">', links["tiktoken-0.13.0-cp314-cp314-win_arm64.whl"])
        self.assertNotIn("data-yanked", links["tiktoken-0.14.0-cp314-cp314-win_arm64.whl"])

    def test_a_yanked_wheel_with_no_reason_is_marked_with_an_empty_one(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gap-wheels.json").write_text(json.dumps({"schema": 1, "wheels": [wheel()]}))
        (tmp / "status.json").write_text(json.dumps({"schema": 1, "wheels": [
            {"project": "tiktoken", "wheel": "tiktoken-0.14.0-cp314-cp314-win_arm64.whl", "status": "yanked", "yank_reason": None},
        ]}))
        self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site", tmp / "status.json"), 0)
        page = (tmp / "site/wheels/simple/tiktoken/index.html").read_text()
        self.assertIn('win_arm64.whl#sha256=', page)
        self.assertIn(' data-yanked="">tiktoken-0.14.0-cp314-cp314-win_arm64.whl</a>', page)
        # The transparency record is copied as it came, with no marker added to it.
        self.assertNotIn("_yanked", (tmp / "site/data/gap-wheels.json").read_text())

    def test_missing_or_malformed_status_warns_and_matches_legacy_output(self):
        wheels = [wheel()]
        baseline = self.build(wheels)
        for bad in (None, "{not json", json.dumps({"schema": 2, "wheels": []}), json.dumps({"schema": 1, "wheels": [{"project": "tiktoken"}]})):
            tmp = Path(tempfile.mkdtemp())
            (tmp / "gap-wheels.json").write_text(json.dumps({"schema": 1, "wheels": wheels}))
            status_path = tmp / "status.json"
            if bad is not None:
                status_path.write_text(bad)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site", status_path), 0)
            self.assertIn("::warning::status.json is missing or unusable", buf.getvalue())
            self.assertEqual(
                (tmp / "site/wheels/simple/index.html").read_bytes(),
                (baseline / "wheels/simple/index.html").read_bytes(),
            )
            self.assertEqual(
                (tmp / "site/wheels/simple/tiktoken/index.html").read_bytes(),
                (baseline / "wheels/simple/tiktoken/index.html").read_bytes(),
            )

    def test_all_in_index_status_produces_byte_identical_output(self):
        wheels = [wheel(), wheel(name="Zope.Interface", file="zope_interface-8.7-cp314-cp314-win_arm64.whl")]
        without = self.build(wheels)
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gap-wheels.json").write_text(json.dumps({"schema": 1, "wheels": wheels}))
        (tmp / "status.json").write_text(json.dumps({
            "schema": 1,
            "wheels": [
                {"project": "tiktoken", "wheel": "tiktoken-0.14.0-cp314-cp314-win_arm64.whl", "status": "in-index"},
                {"project": "Zope.Interface", "wheel": "zope_interface-8.7-cp314-cp314-win_arm64.whl", "status": "in-index"},
            ],
        }))
        self.assertEqual(build_gap_index.build(tmp / "gap-wheels.json", tmp / "site", tmp / "status.json"), 0)
        for rel in ("wheels/simple/index.html", "wheels/simple/tiktoken/index.html", "wheels/simple/zope-interface/index.html"):
            self.assertEqual((tmp / "site" / rel).read_bytes(), (without / rel).read_bytes())
