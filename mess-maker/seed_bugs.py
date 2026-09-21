#!/usr/bin/env python3
"""Inject or revert the seeded defects in dummy-api-server.

    python mess-maker/seed_bugs.py --status          # what is currently broken
    python mess-maker/seed_bugs.py --seed B1         # inject one bug
    python mess-maker/seed_bugs.py --seed all        # inject every bug
    python mess-maker/seed_bugs.py --seed random     # inject one at random
    python mess-maker/seed_bugs.py --revert B1       # put it back
    python mess-maker/seed_bugs.py --revert all      # clean slate

Seeding is idempotent: seeding an already-seeded bug is a no-op, and every
operation verifies the snippet appears exactly once before touching the file.
Exit code is 0 on success, 1 on failure, so you can chain it in scripts.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from bug_catalogue import CATALOGUE, Bug, bug_state, repo_root


def _apply(bug: Bug, root: Path, *, seed: bool) -> str:
    path = root / bug.file
    text = path.read_text(encoding="utf-8")
    source, target = (bug.fixed, bug.broken) if seed else (bug.broken, bug.fixed)
    verb = "seeded" if seed else "reverted"

    if text.count(target) == 1 and text.count(source) == 0:
        return f"  {bug.bug_id}  already {verb}"
    occurrences = text.count(source)
    if occurrences != 1:
        raise SystemExit(
            f"{bug.bug_id}: expected exactly one match in {bug.file}, found {occurrences}.\n"
            f"The file has drifted from the catalogue. Restore it with git, or update "
            f"the snippet in bug_catalogue.py."
        )
    path.write_text(text.replace(source, target, 1), encoding="utf-8")
    return f"  {bug.bug_id}  {verb}  ({bug.title})"


def _resolve(selector: str) -> list[Bug]:
    selector = selector.strip()
    if selector.lower() == "all":
        return list(CATALOGUE.values())
    if selector.lower() == "random":
        return [random.choice(list(CATALOGUE.values()))]
    bugs = []
    for bug_id in selector.split(","):
        bug_id = bug_id.strip().upper()
        if bug_id not in CATALOGUE:
            raise SystemExit(f"Unknown bug id {bug_id!r}. Known: {', '.join(CATALOGUE)}")
        bugs.append(CATALOGUE[bug_id])
    return bugs


def _status(root: Path) -> int:
    print(f"Repository: {root}\n")
    seeded = 0
    for bug in CATALOGUE.values():
        state = bug_state(bug, root)
        seeded += state == "seeded"
        marker = {"seeded": "BROKEN", "clean": "ok    ", "unknown": "???   "}[state]
        logs = "logged" if bug.surfaces_in_logs else "SILENT"
        print(f"  [{marker}] {bug.bug_id}  {bug.title}")
        print(f"            {logs}  |  {bug.symptom}")
        print(f"            test: {bug.test}")
        if bug.notes:
            print(f"            note: {bug.notes}")
        print()
    print(f"{seeded} of {len(CATALOGUE)} bugs currently seeded.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", metavar="IDS", help="bug id(s), 'all', or 'random'")
    group.add_argument("--revert", metavar="IDS", help="bug id(s) or 'all'")
    group.add_argument("--status", action="store_true", help="show what is currently seeded")
    parser.add_argument("--root", type=Path, default=None, help="repository root (auto-detected)")
    args = parser.parse_args()

    root = args.root or repo_root()

    if args.status:
        return _status(root)

    seeding = args.seed is not None
    bugs = _resolve(args.seed if seeding else args.revert)
    print("Seeding:" if seeding else "Reverting:")
    for bug in bugs:
        print(_apply(bug, root, seed=seeding))

    print(
        "\nNext: rebuild the API container so the change is live, then run the "
        "validation suite:\n"
        "  docker compose up -d --build fastapi\n"
        "  docker compose exec fastapi python -m pytest -q tests/test_api_contract.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
