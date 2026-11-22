"""site/check/driver.py, the repo checker's Python side, under CPython with the wheelgap release worker.mjs pins.

CI runs this file with `--with wheelgap==<that version>`; without wheelgap (the plain test run) it's skipped.
"""

import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("wheelgap.suggest_targets")
from wheelgap import origin
from pypi_json import recorded_project, trim_json

SITE = Path(__file__).resolve().parent.parent / "site" / "check"
sys.path.insert(0, str(SITE))
import driver


@pytest.fixture(autouse=True)
def no_installer_index_settings(monkeypatch):
    """The browser has no PIP_* or UV_* index settings. A developer's shell may, and with one set wheelgap counts no
    looked-up package as PyPI's (origin.index_env), so no row would be marked for a fix lookup."""
    while (name := origin.index_env()) is not None:
        monkeypatch.delenv(name)


LOCK = """\
version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "demo"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "fastlib" },
    { name = "purewheel" },
    { name = "winonly", marker = "sys_platform == 'win32'" },
]

[[package]]
name = "fastlib"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/aa/fastlib-2.0.0.tar.gz", hash = "sha256:00", size = 1 }
wheels = [
    { url = "https://files.pythonhosted.org/packages/aa/fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hash = "sha256:00", size = 1 },
    { url = "https://files.pythonhosted.org/packages/aa/fastlib-2.0.0-cp313-cp313-musllinux_1_2_aarch64.whl", hash = "sha256:00", size = 1 },
]

[[package]]
name = "purewheel"
version = "3.1"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/aa/purewheel-3.1-py3-none-any.whl", hash = "sha256:00", size = 1 },
]

[[package]]
name = "winonly"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/aa/winonly-1.0-cp313-cp313-win_amd64.whl", hash = "sha256:00", size = 1 },
]
"""

WORKFLOW = """\
on: push
jobs:
  test:
    runs-on: ubuntu-24.04-arm
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "uv.lock").write_text(LOCK, encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "Dockerfile").write_text("FROM python:3.13-alpine\n", encoding="utf-8")
    return tmp_path


def test_worker_pins_the_tested_wheelgap():
    import wheelgap

    pin = re.search(r'WHEELGAP = "wheelgap==([^"]+)"', (SITE / "worker.mjs").read_text(encoding="utf-8"))
    assert pin and pin.group(1) == wheelgap.__version__


def test_plan_picks_files_like_suggest_targets():
    paths = [
        "README.md",
        "uv.lock",
        "pixi.lock",
        "pyproject.toml",
        "backend/uv.lock",
        "backend/requirements.txt",
        "backend/pixi.lock",
        "backend/pyproject.toml",
        "node_modules/x/uv.lock",
        ".venv/lib/poetry.lock",
        ".github/workflows/ci.yml",
        ".github/workflows/notes.md",
        ".github/workflows/sub/inner.yml",
        "Dockerfile",
        "deploy/Containerfile",
        "deploy/Dockerfile.j2",
        ".devcontainer/Dockerfile",
        ".python-version",
    ]
    plan = json.loads(driver.plan(json.dumps(paths)))
    assert plan["lockfiles"] == [
        {"path": "uv.lock", "offline": True},
        {"path": "pixi.lock", "offline": False},
        {"path": "pyproject.toml", "offline": False},
        {"path": "backend/uv.lock", "offline": True},
        {"path": "backend/requirements.txt", "offline": False},
        {"path": "backend/pixi.lock", "offline": False},
        {"path": "backend/pyproject.toml", "offline": False},
    ]
    assert plan["workflows"] == [".github/workflows/ci.yml"]
    assert plan["dockerfiles"] == ["Dockerfile", "deploy/Containerfile"]
    assert plan["templates"] == ["deploy/Dockerfile.j2"]
    assert plan["python_version"] == ".python-version"


def test_plan_lists_other_requirements_filenames_after_every_exactly_named_file():
    paths = [
        "pyproject.toml",
        "constraints.txt",
        "constraints-dev.txt",
        "requirements/constraints.txt",
        "requirements/README.txt",
        "requirements/docs.txt",
        "requirements/test.txt",
        "requirements/default.txt",
        "requirements/base.txt",
        "requirements/Notes.txt",
        "Requirements-dev.TXT",
        "tests/requirements.txt",
        "tests/requirements/default.txt",
        "requirements-dev.txt",
        "prod-requirements.txt",
        "extra_requirements.txt",
    ]
    plan = json.loads(driver.plan(json.dumps(paths)))
    # No order by how runtime-like a name sounds: autoPick() in check-logic.mjs asks which one when there are several,
    # as `wheelgap DIR` lists them and never picks one.
    assert plan["lockfiles"] == [
        {"path": "pyproject.toml", "offline": False},
        *(
            {"path": p, "offline": False, "other": True}
            for p in [
                "extra_requirements.txt",
                "prod-requirements.txt",
                "requirements-dev.txt",
                "requirements/base.txt",
                "requirements/default.txt",
                "requirements/docs.txt",
                "requirements/test.txt",
            ]
        ),
    ]

    # A root requirements.txt still comes first ahead of other root requirements files.
    with_root = json.loads(driver.plan(json.dumps(["requirements-dev.txt", "requirements.txt", "requirements/default.txt"])))
    assert [entry["path"] for entry in with_root["lockfiles"]] == [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements/default.txt",
    ]
    assert "other" not in with_root["lockfiles"][0]
    # And an exactly-named file deeper in the repo still outranks them, so the page's pick is what it was before.
    nested = json.loads(driver.plan(json.dumps(["requirements-dev.txt", "backend/uv.lock", "backend/pyproject.toml"])))
    assert [entry["path"] for entry in nested["lockfiles"]] == ["backend/uv.lock", "backend/pyproject.toml", "requirements-dev.txt"]


def test_needs_and_check_read_nested_requirements_file_with_include(tmp_path):
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()
    (req_dir / "base.txt").write_text("-r common.txt\npurewheel==3.1\n", encoding="utf-8")
    first = json.loads(driver.needs(str(tmp_path), "requirements/base.txt"))
    assert first["kind"] == "include" and first["path"] == "requirements/common.txt"

    (req_dir / "common.txt").write_text("fastlib==2.0.0\n", encoding="utf-8")
    needed = json.loads(driver.needs(str(tmp_path), "requirements/base.txt"))
    assert {(l["name"], l["version"]) for l in needed["lookups"]} == {("fastlib", "2.0.0"), ("purewheel", "3.1")}

    lookups = {
        "purewheel==3.1": {"info": {"version": "3.1"}, "urls": [{"filename": "purewheel-3.1-py3-none-any.whl"}]},
        "fastlib==2.0.0": {"info": {"version": "2.0.0"}, "urls": [{"filename": "fastlib-2.0.0.tar.gz"}]},
    }
    res = json.loads(driver.check(str(tmp_path), "requirements/base.txt", options(), json.dumps(lookups)))
    assert res["looked_up"] is True
    assert res["packages"] == 2
    assert [row["name"] for row in res["rows"]] == ["fastlib"]


def test_detect_reads_ci_and_dockerfiles(repo):
    d = json.loads(driver.detect(str(repo)))
    assert d["platforms_from"] == "ci" and d["python_from"] == "ci"
    assert set(d["platforms"]) == {"linux-aarch64", "musl-x86_64"}
    assert d["pythons"] == ["3.13"]
    assert {(f["kind"], f["value"], f["path"]) for f in d["found"]} >= {
        ("target", "linux-aarch64", ".github/workflows/ci.yml"),
        ("target", "musl-x86_64", "deploy/Dockerfile"),
    }


def test_detect_falls_back_to_python_version_then_defaults(tmp_path):
    d = json.loads(driver.detect(str(tmp_path)))
    assert d["platforms_from"] == "default" and d["python_from"] == "default"
    assert d["platforms"] == ["linux-x86_64", "linux-aarch64", "macos-arm64", "win-amd64"]
    (tmp_path / ".python-version").write_text("# pinned\n3.12.4\n", encoding="utf-8")
    d = json.loads(driver.detect(str(tmp_path)))
    assert d["pythons"] == ["3.12"] and d["python_from"] == ".python-version"


def options(**kw):
    return json.dumps({"pythons": ["3.13"], "platforms": ["linux-x86_64", "linux-aarch64", "musl-aarch64"]} | kw)


def test_check_lists_gap_rows_and_counts(repo):
    r = json.loads(driver.check(str(repo), "uv.lock", options()))
    assert r["lockfile"] == "uv.lock" and r["outside_lock"] == [] and r["skipped"] == ["demo"]
    assert r["looked_up"] is False and r["private"] == []  # read from the lock's own files; demo is the project
    assert [row["name"] for row in r["rows"]] == ["fastlib"]
    fast = r["rows"][0]
    assert fast["gaps"] == ["3.13 linux-aarch64"]
    assert fast["keep"] == ["3.13 linux-x86_64", "3.13 musl-aarch64"]
    assert fast["unknown"] == [] and fast["lookup"] is True
    assert fast["statuses"]["3.13 linux-aarch64"] == "source"
    # winonly isn't installed off Windows: n/a, not a gap, and not counted.
    assert r["per_target"]["3.13 linux-x86_64"] == {"wheel": 2, "source": 0, "missing": 0, "unknown": 0}
    assert r["per_target"]["3.13 linux-aarch64"] == {"wheel": 1, "source": 1, "missing": 0, "unknown": 0}


def test_check_doesnt_count_pythons_outside_the_lock(repo):
    (repo / "uv.lock").write_text(LOCK.replace('">=3.13"', '">=3.13, <3.14"'), encoding="utf-8")
    r = json.loads(driver.check(str(repo), "uv.lock", options(pythons=["3.13", "3.14"])))
    assert r["outside_lock"] == ["3.14"]
    assert all(g.startswith("3.13 ") for row in r["rows"] for g in row["gaps"])
    assert r["per_target"]["3.14 linux-x86_64"] == {"wheel": 0, "source": 0, "missing": 0, "unknown": 0}


PYLOCK = """\
lock-version = "1.0"
created-by = "pip"
requires-python = ">=3.13, <3.14"

[[packages]]
name = "fastlib"
version = "2.0.0"
wheels = [
    { name = "fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", url = "https://files.pythonhosted.org/packages/aa/fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hashes = { sha256 = "00" } },
]
"""


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("uv-py312.lock", LOCK.replace('">=3.13"', '">=3.13, <3.14"')),
        ("envs/pylock.dev.toml", PYLOCK),
    ],
)
def test_a_lockfile_named_by_its_reader_is_checked_offline(repo, name, text):
    # A link can name a lockfile plan() doesn't list. wheelgap reads it by the reader its name picks (file_kind):
    # checked as a lookups file, the Python its lock leaves out (3.14) would show false gaps, not `outside_lock`.
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")
    assert json.loads(driver.needs(str(repo), name)) == {"lookups": [], "total": 0}
    r = json.loads(driver.check(str(repo), name, options(pythons=["3.13", "3.14"]), "{}"))
    assert "error" not in r, r
    assert r["looked_up"] is False and r["outside_lock"] == ["3.14"]
    assert all(g.startswith("3.13 ") for row in r["rows"] for g in row["gaps"])
    assert r["per_target"]["3.14 linux-x86_64"] == {"wheel": 0, "source": 0, "missing": 0, "unknown": 0}


def test_offline_follows_the_reader_not_the_exact_name():
    offline = {
        "uv.lock": True, "a/pylock.toml": True, "poetry.lock": True, "pdm.lock": True, "pylock.dev.toml": True,
        "uv-py312.lock": True, "Pipfile.lock": False, "pixi.lock": False, "pyproject.toml": False,
        "requirements.txt": False, "requirements-dev.lock": False, "requirements.uv.lock": False, "dev.in": False,
        "script.py.lock": False, "README.md": False,
    }
    assert {p: driver._reads_offline(p) for p in offline} == offline


def test_check_refuses_lockfiles_that_need_an_index(repo):
    assert json.loads(driver.check(str(repo), "uv.lock", options(platforms=["amiga"])))["kind"] == "targets"
    (repo / "uv.lock").write_text("not toml [", encoding="utf-8")
    bad = json.loads(driver.check(str(repo), "uv.lock", options()))
    assert bad["kind"] == "source" and str(repo) not in bad["error"]


def test_check_reports_a_lockfile_that_needs_the_index_for_its_missing_files(repo):
    # A poetry.lock is offered as checkable, but wheelgap reads it offline only when every package lists its
    # files; one that doesn't would need a PyPI lookup the page can't make offline, so check() says needs-index
    # rather than surfacing wheelgap's API-oriented "set offline=False" error as if the lockfile were unreadable.
    (repo / "poetry.lock").write_text(
        '[[package]]\nname = "demo"\nversion = "0.1.0"\n\n[metadata]\nlock-version = "2.1"\n'
        'python-versions = ">=3.13"\ncontent-hash = "abc123"\n',
        encoding="utf-8",
    )
    r = json.loads(driver.check(str(repo), "poetry.lock", options()))
    assert r["kind"] == "needs-index"
    # A pixi.lock records only the file pixi picked per platform, so it's checked from PyPI lookups instead.
    (repo / "pixi.lock").write_text("version: 7" + chr(10) + "environments:" + chr(10) + "  default: {}" + chr(10) + "packages: []" + chr(10), encoding="utf-8")
    pixi = json.loads(driver.check(str(repo), "pixi.lock", options(), "{}"))
    assert "error" not in pixi and pixi["rows"] == []


def wheel(name, requires_python=None):
    return {"filename": name, "yanked": False, "requires_python": requires_python, "packagetype": "bdist_wheel"}


def test_fixes_names_the_nearest_release_with_a_wheel(repo):
    r = json.loads(driver.check(str(repo), "uv.lock", options()))
    releases = {
        "fastlib": {
            "2.0.0": [wheel("fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.whl")],
            "2.1.0": [wheel("fastlib-2.1.0-cp313-cp313-manylinux_2_17_x86_64.whl")],  # still no aarch64
            "2.2.0": [
                wheel("fastlib-2.2.0-cp313-cp313-manylinux_2_17_x86_64.whl"),
                wheel("fastlib-2.2.0-cp313-cp313-manylinux_2_17_aarch64.whl"),
                wheel("fastlib-2.2.0-cp313-cp313-musllinux_1_2_aarch64.whl"),
            ],
        }
    }
    fx = json.loads(driver.fixes(json.dumps(releases), json.dumps(r["rows"])))
    assert fx == {"fastlib==2.0.0": {"found": {"3.13 linux-aarch64": "2.2.0"}, "loses": []}}
    # A package that wasn't looked up gets no answer at all (the page says "not looked up", not "no fix").
    assert json.loads(driver.fixes("{}", json.dumps(r["rows"]))) == {}


def test_a_private_index_package_is_never_looked_up_on_pypi(repo):
    lock = (
        LOCK.replace('{ name = "purewheel" },', '{ name = "purewheel" },\n    { name = "corp-utils" },')
        + """
[[package]]
name = "corp-utils"
version = "1.0"
source = { registry = "https://pkgs.corp.example/simple" }
sdist = { url = "https://pkgs.corp.example/files/corp-utils-1.0.tar.gz", hash = "sha256:00", size = 1 }
"""
    )
    (repo / "uv.lock").write_text(lock, encoding="utf-8")
    r = json.loads(driver.check(str(repo), "uv.lock", options()))
    corp = next(row for row in r["rows"] if row["name"] == "corp-utils")
    assert corp["lookup"] is False
    squatted = {"corp-utils": {"9.9": [wheel("corp_utils-9.9-py3-none-any.whl")]}}
    assert "corp-utils==1.0" not in json.loads(driver.fixes(json.dumps(squatted), json.dumps(r["rows"])))


def test_fixes_reports_a_release_that_only_trades_one_gap_for_another(repo):
    r = json.loads(driver.check(str(repo), "uv.lock", options()))
    releases = {
        "fastlib": {
            "2.0.0": [wheel("fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.whl")],
            # has the aarch64 wheel the pin lacks, but drops x86_64 and musl: not a fix, yet not "nothing newer"
            "2.1.0": [wheel("fastlib-2.1.0-cp313-cp313-manylinux_2_17_aarch64.whl")],
        }
    }
    fx = json.loads(driver.fixes(json.dumps(releases), json.dumps(r["rows"])))
    assert fx == {"fastlib==2.0.0": {"found": {}, "loses": ["3.13 linux-aarch64"]}}


@pytest.mark.parametrize(
    "case", ["match", "version", "target", "private", "malformed", "requires_python"]
)
def test_gap_wheels_reuse_cli_checks(repo, case):
    gapwheels = pytest.importorskip("wheelgap.gapwheels")
    lockfile = repo / "uv.lock"
    entry = {
        "name": "fastlib",
        "version": "2.0.0",
        "wheel": "fastlib-2.0.0-cp313-cp313-win_amd64.whl",
        "sha256": "a" * 64,
        "requires_python": ">=3.13",
    }
    if case == "private":
        lockfile.write_text(
            LOCK.replace(
                'name = "fastlib"\nversion = "2.0.0"\nsource = { registry = "https://pypi.org/simple" }',
                'name = "fastlib"\nversion = "2.0.0"\nsource = { registry = "https://private.invalid/simple" }',
            ),
            encoding="utf-8",
        )
    elif case == "version":
        entry.update(version="2.0.1", wheel="fastlib-2.0.1-cp313-cp313-win_amd64.whl")
    elif case == "target":
        entry["wheel"] = "fastlib-2.0.0-cp313-cp313-win_arm64.whl"
    elif case == "malformed":
        entry["sha256"] = "bad"
    elif case == "requires_python":
        entry["requires_python"] = ">=3.14"
    options = {"pythons": ["3.13"], "platforms": ["win-amd64"]}
    driver.check(str(repo), lockfile.name, json.dumps(options))
    result = json.loads(
        driver.gap_wheels(json.dumps({"schema": gapwheels.SCHEMA, "wheels": [entry]}))
    )
    if case == "match":
        assert [(cell["name"], cell["target"]) for cell in result["cells"]] == [
            ("fastlib", "3.13 win-amd64")
        ]
        assert "[[tool.uv.index]]" in result["text"]
        assert "fastlib" in result["text"]
        assert result["unofficial"] == gapwheels.UNOFFICIAL
    else:
        assert result == {"cells": [], "text": "", "unofficial": ""}


def test_plan_lists_a_pyproject_after_the_lockfiles_in_its_folder():
    plan = json.loads(driver.plan(json.dumps(["pyproject.toml", "uv.lock", "sub/pyproject.toml", "sub/uv.lock"])))
    assert [l["path"] for l in plan["lockfiles"]] == ["uv.lock", "pyproject.toml", "sub/uv.lock", "sub/pyproject.toml"]
    assert [l["offline"] for l in plan["lockfiles"]] == [True, False, True, False]


def test_needs_lists_the_lookups_a_requirements_file_needs(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy==2.3.4\nfastlib>=2,<3\n\n# notes\n", encoding="utf-8")
    n = json.loads(driver.needs(str(tmp_path), "requirements.txt"))
    assert n["lookups"] == [{"name": "numpy", "version": "2.3.4"}, {"name": "fastlib", "version": None}]


def test_needs_skips_private_index_packages(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "--index-url https://example.invalid/simple\nnumpy==2.3.4\n", encoding="utf-8"
    )
    assert json.loads(driver.needs(str(tmp_path), "requirements.txt"))["lookups"] == []
    r = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), "{}"))
    assert r["skipped"] == ["numpy"] and r["rows"] == []
    # The page says why nothing was checked, and never "all 0 packages have a wheel": `private` names them.
    assert r["private"] == ["numpy"] and r["packages"] == 0 and r["looked_up"] is True
    # An extra index is another index too: pip may take any of the file's packages from it.
    (tmp_path / "requirements.txt").write_text(
        "--extra-index-url https://download.example.invalid/whl\nnumpy==2.3.4\nfastlib>=2\n", encoding="utf-8"
    )
    assert json.loads(driver.needs(str(tmp_path), "requirements.txt"))["lookups"] == []
    # Even handed an answer for one of them, check() fills nothing in.
    r = json.loads(
        driver.check(str(tmp_path), "requirements.txt", options(), json.dumps({"numpy==2.3.4": PYPI_DOC(numpy_urls)}))
    )
    assert r["private"] == ["fastlib", "numpy"] and r["packages"] == 0 and r["rows"] == []


def test_needs_reads_a_pyprojects_direct_requirements(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["numpy==2.3.4", "demo"]\n',
        encoding="utf-8",
    )
    n = json.loads(driver.needs(str(tmp_path), "pyproject.toml"))
    assert n["lookups"] == [{"name": "numpy", "version": "2.3.4"}]


@pytest.mark.parametrize("settings", [
    '[tool.uv.sources]\nmylib = { workspace = true }\n',
    '[[tool.uv.index]]\nurl = "https://example.invalid/simple"\n',
])
def test_pyproject_with_other_sources_reports_every_private_dependency(tmp_path, settings):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "myapp"\ndependencies = ["fastapi", "numpy", "mylib"]\n' + settings,
        encoding="utf-8",
    )
    assert json.loads(driver.needs(str(tmp_path), "pyproject.toml"))["lookups"] == []
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert (r["listed"], r["packages"], r["private_count"]) == (3, 0, 3)
    assert r["private"] == r["skipped"] == ["fastapi", "mylib", "numpy"]
    assert r["looked_up"] is True and r["rows"] == []


def test_private_count_counts_entries_not_distinct_names(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '''[project]
name = "demo"
dependencies = ['numpy; python_version < "3.14"', 'numpy; python_version >= "3.14"']
[tool.uv.sources]
demo = { workspace = true }
''', encoding="utf-8",
    )
    assert json.loads(driver.needs(str(tmp_path), "pyproject.toml"))["lookups"] == []
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert (r["listed"], r["packages"], r["private_count"]) == (2, 0, 2)
    assert r["private"] == r["skipped"] == ["numpy"]


def test_private_count_does_not_include_other_skipped_packages(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '''[project]
name = "demo"
dependencies = ["numpy", "localpkg @ file:///localpkg"]
[tool.uv.sources]
demo = { workspace = true }
''', encoding="utf-8",
    )
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert (r["listed"], r["packages"], r["private_count"]) == (2, 0, 1)
    assert r["private"] == ["numpy"] and r["skipped"] == ["localpkg", "numpy"]


def test_needs_names_a_missing_include_and_works_once_its_fetched(tmp_path):
    (tmp_path / "requirements.txt").write_text("-r dev.txt\nnumpy==2.3.4\n", encoding="utf-8")
    n = json.loads(driver.needs(str(tmp_path), "requirements.txt"))
    assert n["kind"] == "include" and n["path"] == "dev.txt" and str(tmp_path) not in n["error"]
    (tmp_path / "dev.txt").write_text("fastlib>=2\n", encoding="utf-8")
    assert [l["name"] for l in json.loads(driver.needs(str(tmp_path), "requirements.txt"))["lookups"]] == [
        "fastlib",
        "numpy",
    ]


def test_needs_refuses_an_include_outside_the_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("-r ../shared.txt\nnumpy==2.3.4\n", encoding="utf-8")
    n = json.loads(driver.needs(str(repo), "requirements.txt"))
    # No path for the worker to fetch: it would be read from outside the repo's folder.
    assert n["kind"] == "include" and n["path"] is None
    assert "outside the repository" in n["error"] and str(tmp_path) not in n["error"]


def test_needs_lists_each_lookup_once_and_leaves_other_errors_to_check(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "numpy==2.3.4\nNumPy==2.3.4 ; python_version >= '3.13'\nfastlib\n", encoding="utf-8"
    )
    n = json.loads(driver.needs(str(tmp_path), "requirements.txt"))
    assert n["lookups"] == [{"name": "numpy", "version": "2.3.4"}, {"name": "fastlib", "version": None}]
    # A pyproject.toml with only tool settings: nothing to look up, and check() says why it can't be read.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    assert json.loads(driver.needs(str(tmp_path), "pyproject.toml"))["kind"] == "source"
    bad = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert bad["kind"] == "source" and "no [project] table" in bad["error"] and str(tmp_path) not in bad["error"]


def test_a_lockfile_that_lists_its_files_needs_no_lookups(repo):
    assert json.loads(driver.needs(str(repo), "uv.lock")) == {"lookups": [], "total": 0}


def test_needs_and_check_read_a_pipfile_lock(tmp_path):
    pipfile = {
        "_meta": {
            "sources": [{"url": "https://pypi.org/simple", "name": "pypi", "verify_ssl": True}],
            "hash": {"sha256": "x"},
        },
        "default": {
            "numpy": {"version": "==2.3.4", "hashes": ["sha256:x"]},
            "corp-utils": {"version": "==2.0", "hashes": ["sha256:z"], "index": "corp"},
        },
        "develop": {},
    }
    (tmp_path / "Pipfile.lock").write_text(json.dumps(pipfile), encoding="utf-8")
    n = json.loads(driver.needs(str(tmp_path), "Pipfile.lock"))
    assert n["lookups"] == [{"name": "numpy", "version": "2.3.4"}]  # corp-utils is bound to another index
    docs = {"numpy==2.3.4": PYPI_DOC(numpy_urls)}
    r = json.loads(driver.check(str(tmp_path), "Pipfile.lock", options(), json.dumps(docs)))
    assert r["skipped"] == ["corp-utils"]
    assert [row["name"] for row in r["rows"]] == ["numpy"]
    assert r["rows"][0]["gaps"] == ["3.13 linux-aarch64", "3.13 musl-aarch64"]


numpy_urls = [
    wheel("numpy-2.3.4-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"),
    wheel("numpy-2.3.4.tar.gz"),
]
PYPI_DOC = lambda urls: {"info": {}, "releases": {}, "urls": urls}


def test_check_fills_requirements_from_canned_pypi_json(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy==2.3.4\nfastlib>=2,<3\nmissing==1.0\n", encoding="utf-8")
    docs = {
        "numpy==2.3.4": PYPI_DOC(numpy_urls),
        # fastlib 2.2.0 only supports Python 3.14, so the range resolves to 2.0.0 on 3.13 and 2.2.0 on 3.14.
        "fastlib": {
            "info": {},
            "urls": [],
            "releases": {
                "2.0.0": [wheel("fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.whl"), wheel("fastlib-2.0.0.tar.gz")],
                "2.2.0": [
                    wheel("fastlib-2.2.0-cp314-cp314-manylinux_2_17_x86_64.whl", requires_python=">=3.14"),
                    wheel("fastlib-2.2.0-cp314-cp314-manylinux_2_17_aarch64.whl", requires_python=">=3.14"),
                    wheel("fastlib-2.2.0.tar.gz", requires_python=">=3.14"),
                ],
            },
        },
        "missing==1.0": None,  # PyPI answered 404: unknown, never a gap
    }
    r = json.loads(driver.check(str(tmp_path), "requirements.txt", options(pythons=["3.13", "3.14"]), json.dumps(docs)))
    assert r["skipped"] == [] and r["packages"] == 4  # fastlib resolves to one row per Python
    numpy = next(row for row in r["rows"] if row["name"] == "numpy")
    assert numpy["statuses"]["3.13 linux-x86_64"] == "wheel"  # the cp313 x86_64 wheel
    assert len(numpy["gaps"]) == 5 and "3.13 linux-x86_64" not in numpy["gaps"]
    assert numpy["lookup"] is True
    assert numpy["statuses"]["3.13 linux-x86_64"] == "wheel" and numpy["lookup"] is True
    fast = [row for row in r["rows"] if row["name"] == "fastlib"]
    assert {(row["version"], tuple(row["gaps"])) for row in fast} == {
        ("2.0.0", ("3.13 linux-aarch64", "3.13 musl-aarch64")),
        ("2.2.0", ("3.14 musl-aarch64",)),
    }
    gone = next(row for row in r["rows"] if row["name"] == "missing")
    assert gone["gaps"] == [] and gone["lookup"] is False and len(gone["unknown"]) == 6  # unknown on every target
    assert gone["gaps"] == [] and gone["lookup"] is False
    # fixes() reads the same releases mapping, so the range's 2.0.0 row gets an answer like a lockfile's.
    fx = json.loads(driver.fixes(json.dumps({"fastlib": docs["fastlib"]["releases"]}), json.dumps(fast)))
    assert set(fx) == {"fastlib==2.0.0", "fastlib==2.2.0"} and fx["fastlib==2.0.0"]["found"] == {}


def test_check_fills_a_pyproject_from_canned_pypi_json(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["numpy==2.3.4", "demo"]\n', encoding="utf-8"
    )
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), json.dumps({"numpy==2.3.4": PYPI_DOC(numpy_urls)})))
    assert r["skipped"] == [] and r["packages"] == 1  # demo is the project itself: not a row
    assert [row["name"] for row in r["rows"]] == ["numpy"]
    assert r["rows"][0]["gaps"] == ["3.13 linux-aarch64", "3.13 musl-aarch64"]


def test_a_free_threaded_python_is_resolved_as_its_major_minor(tmp_path):
    # Requires-Python is compared with a version, and "3.14t" isn't one. Handed over as the page writes it, every
    # file that has a Requires-Python is ruled out, so a pin read as "can't install" on a free-threaded target.
    (tmp_path / "requirements.txt").write_text("numpy==2.3.4\nfastlib>=2\n", encoding="utf-8")
    docs = {
        "numpy==2.3.4": PYPI_DOC(
            [
                wheel("numpy-2.3.4-cp314-cp314t-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", ">=3.11"),
                wheel("numpy-2.3.4.tar.gz", ">=3.11"),
            ]
        ),
        "fastlib": {
            "info": {},
            "urls": [],
            "releases": {"2.0.0": [wheel("fastlib-2.0.0-cp314-cp314t-manylinux_2_17_x86_64.whl", ">=3.13")]},
        },
    }
    for pythons in (["3.14t"], ["3.13", "3.14t"]):
        opts = options(pythons=pythons, platforms=["linux-x86_64"])
        r = json.loads(driver.check(str(tmp_path), "requirements.txt", opts, json.dumps(docs)))
        assert r["per_target"]["3.14t linux-x86_64"] == {"wheel": 2, "source": 0, "missing": 0, "unknown": 0}, pythons
        assert not [row for row in r["rows"] if "3.14t linux-x86_64" in row["gaps"] + row["unknown"]], pythons


def test_a_pyproject_is_checked_on_pythons_outside_its_requires_python(tmp_path):
    # `uvx wheelgap pyproject.toml -p 3.13` checks 3.13 whatever requires-python says ("checked anyway because you
    # asked for them"): PyPI has the release's files for every Python, unlike a uv.lock.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.14"\ndependencies = ["numpy==2.3.4"]\n',
        encoding="utf-8",
    )
    docs = json.dumps({"numpy==2.3.4": PYPI_DOC(numpy_urls)})
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), docs))
    assert r["outside_lock"] == [] and r["looked_up"] is True
    assert r["per_target"]["3.13 linux-x86_64"] == {"wheel": 1, "source": 0, "missing": 0, "unknown": 0}
    assert [row["gaps"] for row in r["rows"]] == [["3.13 linux-aarch64", "3.13 musl-aarch64"]]


def test_a_requirement_no_target_installs_is_not_a_package_of_the_result(tmp_path):
    # As the CLI counts them: winonly's marker rules it out on every target here, so it's no row and not in the total.
    (tmp_path / "requirements.txt").write_text(
        'numpy==2.3.4\nwinonly==1.0 ; sys_platform == "win32"\n', encoding="utf-8"
    )
    docs = {
        "numpy==2.3.4": PYPI_DOC(numpy_urls),
        "winonly==1.0": PYPI_DOC([wheel("winonly-1.0-cp313-cp313-win_amd64.whl")]),
    }
    r = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(docs)))
    assert r["packages"] == 1 and [row["name"] for row in r["rows"]] == ["numpy"]


PIXI = """\
version: 6
environments:
  default:
    channels:
    - url: https://conda.anaconda.org/conda-forge/
    indexes:
    - https://pypi.org/simple
    packages:
      linux-64:
      - conda: https://conda.anaconda.org/conda-forge/linux-64/python-3.13.1-h9a34f23_5_cp313.conda
      - pypi: https://files.pythonhosted.org/packages/aa/bb/fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
packages:
- conda: https://conda.anaconda.org/conda-forge/linux-64/python-3.13.1-h9a34f23_5_cp313.conda
  sha256: 0000000000000000000000000000000000000000000000000000000000000000
  md5: 00000000000000000000000000000000
  license: Python-2.0
  size: 1
  timestamp: 1
- pypi: https://files.pythonhosted.org/packages/aa/bb/fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
  name: fastlib
  version: 2.0.0
  sha256: 0000000000000000000000000000000000000000000000000000000000000000
"""


def test_a_pixi_lock_is_looked_up_package_by_package(tmp_path):
    # A pixi.lock says where each file came from (here PyPI's own file host), so its packages are looked up as the
    # CLI does. It never says the whole input is PyPI-only, which must not get every package skipped.
    (tmp_path / "pixi.lock").write_text(PIXI, encoding="utf-8")
    n = json.loads(driver.needs(str(tmp_path), "pixi.lock"))
    assert n["lookups"] == [{"name": "fastlib", "version": "2.0.0"}]
    docs = {
        "fastlib==2.0.0": PYPI_DOC(
            [
                wheel("fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"),
                wheel("fastlib-2.0.0.tar.gz"),
            ]
        )
    }
    opts = options(platforms=["linux-x86_64", "linux-aarch64"])
    r = json.loads(driver.check(str(tmp_path), "pixi.lock", opts, json.dumps(docs)))
    assert r["packages"] == 1 and r["skipped"] == ["python"] and r["private"] == []  # python is the conda package
    assert [(row["name"], row["gaps"]) for row in r["rows"]] == [("fastlib", ["3.13 linux-aarch64"])]
    # As with --suggest: the lock doesn't record the index as PyPI, so no fix is looked up for it.
    assert r["rows"][0]["lookup"] is False
    # With no answer from PyPI it's unknown on every target, never judged on the one file the lock recorded.
    r = json.loads(driver.check(str(tmp_path), "pixi.lock", opts, "{}"))
    assert [(row["gaps"], len(row["unknown"])) for row in r["rows"]] == [([], 2)]


def test_an_answer_with_no_file_list_is_unknown_never_a_gap(tmp_path):
    # A 200 that isn't PyPI's JSON (a proxy's page, say). wheelgap reads a missing `urls` as a release with no files,
    # which is "can't install": a gap nobody has. A range without `releases` already says "unknown" itself.
    (tmp_path / "requirements.txt").write_text("numpy==2.3.4\nfastlib\nranged>=2\n", encoding="utf-8")
    docs = {
        "numpy==2.3.4": {"message": "not PyPI's JSON"},
        "fastlib": {"info": {"version": "2.0.0"}},
        "ranged": {"info": {}},
    }
    r = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(docs)))
    assert r["packages"] == 3 and all(sum(c.values()) == c["unknown"] == 3 for c in r["per_target"].values())
    assert [(row["name"], row["gaps"], len(row["unknown"]), row["lookup"]) for row in r["rows"]] == [
        ("numpy", [], 3, False),
        ("fastlib", [], 3, False),
        ("ranged", [], 3, False),
    ]


@pytest.mark.parametrize("requirement", ["numpy==2.3.4", "numpy>=2.3,<2.4", "numpy"])
def test_trimmed_recorded_json_keeps_check_and_fixes_answers(tmp_path, requirement):
    project = recorded_project()
    pinned = requirement == "numpy==2.3.4"
    doc = {"info": project["info"], "urls": project["releases"]["2.3.4"]} if pinned else project
    docs = {"numpy==2.3.4" if pinned else "numpy": doc}
    releases = {"numpy": project["releases"]}
    trimmed, trimmed_releases = trim_json(docs), trim_json(releases, releases=True)
    assert len(json.dumps(trimmed)) < len(json.dumps(docs)) / 2
    assert len(json.dumps(trimmed_releases)) < len(json.dumps(releases)) / 2
    (tmp_path / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    answers = []
    for lookups, rel in [(docs, releases), (trimmed, trimmed_releases)]:
        result = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(lookups)))
        fixes = json.loads(driver.fixes(json.dumps(rel), json.dumps(result["rows"])))
        answers.append((result, fixes))
    assert answers[0] == answers[1]
    result, fixes = answers[1]
    assert result["packages"] == 1 and result["rows"][0]["lookup"] is True
    if requirement != "numpy":
        # The recorded 2.4.0 files are yanked: they must not hide the next usable fix.
        assert fixes["numpy==2.3.4"]["found"] == {"3.13 linux-aarch64": "2.5.5"}
    else:
        assert fixes == {"numpy==2.5.5": {"found": {}, "loses": []}}


@pytest.mark.parametrize("requirement", ["fastlib==1.0", "fastlib>=1", "fastlib"])
def test_trimming_preserves_yanks_python_constraints_and_invalid_releases(tmp_path, requirement):
    old = [wheel("fastlib-1.0-cp313-cp313-manylinux_2_17_x86_64.whl", ">=3.13,<3.14"),
           wheel("fastlib-1.0.tar.gz", ">=3.13,<3.14")]
    newer = [wheel("fastlib-2.0-cp314-cp314-manylinux_2_17_x86_64.whl", ">=3.14"),
             wheel("fastlib-2.0-cp314-cp314-manylinux_2_17_aarch64.whl", ">=3.14")]
    releases = {"fastlib": {
        "1.0": old, "2.0": newer,
        "3.0": [{**wheel("fastlib-3.0-py3-none-any.whl"), "yanked": True}],
        "4.0": [wheel("fastlib-4.0-py3-none-any.whl"), {}],  # reject the whole list, never filter the bad entry out
    }}
    project = {"info": {"version": "1.0"}, "urls": old, "releases": releases["fastlib"]}
    docs = {"fastlib==1.0" if "==" in requirement else "fastlib": project}
    (tmp_path / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    answers = []
    for lookups, rel in [(docs, releases), (trim_json(docs), trim_json(releases, releases=True))]:
        result = json.loads(driver.check(str(tmp_path), "requirements.txt", options(pythons=["3.13", "3.14"]), json.dumps(lookups)))
        answers.append((result, json.loads(driver.fixes(json.dumps(rel), json.dumps(result["rows"])))))
    assert answers[0] == answers[1]
    if requirement == "fastlib>=1":
        assert {r["version"] for r in answers[1][0]["rows"]} == {"1.0", "2.0"}


@pytest.mark.parametrize("requirement", ["fastlib==1.0", "fastlib>=1", "fastlib"])
@pytest.mark.parametrize("doc", [None, [], {}, {"info": {"version": "1.0"}}, {"urls": None},
    {"urls": "bad"}, {"urls": [None]}, {"urls": [{}]}, {"urls": [{"filename": None}]},
    {"releases": {"1.0": [{}]}}])
def test_trimming_bad_json_keeps_it_unknown(tmp_path, requirement, doc):
    (tmp_path / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    docs = {"fastlib==1.0" if "==" in requirement else "fastlib": doc}
    before = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(docs)))
    after = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(trim_json(docs))))
    assert before == after
    assert after["rows"][0]["gaps"] == [] and len(after["rows"][0]["unknown"]) == 3
    assert after["rows"][0]["lookup"] is False


@pytest.mark.parametrize("releases", [None, [], {}, {"1.0": None}, {"1.0": []}])
def test_trimming_preserves_empty_lists_and_range_fallback(tmp_path, releases):
    (tmp_path / "requirements.txt").write_text("fastlib>=1\n", encoding="utf-8")
    docs = {"fastlib": {"info": {"version": "1.0"}, "urls": [wheel("fastlib-1.0.tar.gz")], "releases": releases}}
    before = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(docs)))
    after = json.loads(driver.check(str(tmp_path), "requirements.txt", options(), json.dumps(trim_json(docs))))
    assert before == after
    # Non-mapping releases falls back to info.version + urls; an empty mapping does not.
    assert bool(after["rows"][0]["gaps"]) == (not isinstance(releases, dict))
    raw_releases = {"fastlib": releases}
    assert driver.fixes(json.dumps(raw_releases), json.dumps(after["rows"])) == driver.fixes(
        json.dumps(trim_json(raw_releases, releases=True)), json.dumps(after["rows"]))


def test_the_result_counts_the_packages_a_file_lists(tmp_path):
    # No dependencies is different from dependencies that aren't installed on the targets picked, which is an answer.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert "error" not in r and (r["listed"], r["packages"], r["skipped"], r["rows"]) == (0, 0, [], [])
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = [\'winonly==1.0 ; sys_platform == "win32"\']\n',
        encoding="utf-8",
    )
    r = json.loads(driver.check(str(tmp_path), "pyproject.toml", options(), "{}"))
    assert (r["listed"], r["packages"], r["skipped"], r["rows"]) == (1, 0, [], [])
    assert r["private_count"] == 0
