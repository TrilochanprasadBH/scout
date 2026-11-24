#!/usr/bin/env python3
"""Show which stages exist, whether the stubs fail, and whether the reference passes.

    python scripts/status.py

Two columns per stage, because this project ships a learner workspace and an answer:

  src        the stub. It must fail, otherwise the stage is already done for you.
  reference  the answer. It must pass, otherwise the stage is broken.

Exit code is zero only when every stage's reference passes and every stub fails. That is a
stronger gate than `triage`'s, which ran only the stubs and therefore always reported 0 of 7.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

SHARED = (
    "__init__.py",
    "corpus.py",
    "evalmetrics.py",
    "gold.py",
    "model.py",
    "search.py",
    "stats.py",
    "text.py",
)


def run(test: pathlib.Path, impl: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(test)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"IMPL": impl, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    ok = result.returncode == 0
    detail = ""
    if not ok:
        tail = [line for line in result.stderr.splitlines() if line.strip()]
        detail = tail[-1][:58] if tail else ""
    return ok, detail


def check_shared() -> list[str]:
    problems = []
    for name in SHARED:
        left = (ROOT / "src" / "scout" / name).read_bytes()
        right = (ROOT / "reference" / "scout" / name).read_bytes()
        if left != right:
            problems.append(f"{name} differs between src/ and reference/")
    return problems


def main() -> int:
    stages = sorted(p for p in (ROOT / "stages").iterdir() if p.is_dir())
    if not stages:
        print("no stages found")
        return 1

    healthy = 0
    for stage in stages:
        tests = sorted(stage.glob("test_*.py"))
        if not tests:
            print(f"  {stage.name:<20} no tests")
            continue
        stub_ok, stub_detail = run(tests[0], "src")
        reference_ok, reference_detail = run(tests[0], "reference")
        healthy += (not stub_ok) and reference_ok
        print(
            f"  {stage.name:<20} src {'PASS' if stub_ok else 'fail':<5}"
            f" reference {'PASS' if reference_ok else 'fail':<5}"
            f"{'' if reference_ok else reference_detail}"
        )

    print(f"\n  {healthy} of {len(stages)} stages healthy")

    extra = sorted((ROOT / "tests").glob("test_*.py")) if (ROOT / "tests").exists() else []
    if extra:
        print()
        ok = 0
        for test in extra:
            passed, detail = run(test, "src")
            ok += passed
            print(f"  {test.name:<20} {'PASS' if passed else 'fail'}{'' if passed else detail}")
        print(f"  {ok} of {len(extra)} cross-cutting test files passing")
        healthy += ok
        total = len(stages) + len(extra)
    else:
        total = len(stages)

    problems = check_shared()
    if problems:
        print("  shared modules drifted:")
        for problem in problems:
            print(f"    {problem}")
    else:
        print("  shared modules identical in src/ and reference/")

    return 0 if healthy == total and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
