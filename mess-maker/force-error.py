#!/usr/bin/env python3
"""Exercise the API so a seeded defect actually fires.

Each mode maps 1:1 to an entry in bug_catalogue.py. A mode reports FAILED when
the API misbehaves, which is the signal that the seeded bug reproduced.

    python force-error.py --bug B1
    python force-error.py --bug random
    python force-error.py --all

Nothing here injects bugs. Use seed_bugs.py for that.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from random import randint

import requests

API_URL = os.getenv("API_URL", "http://fastapi:8000").rstrip("/")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))


class Outcome:
    def __init__(self, bug_id: str, reproduced: bool, detail: str):
        self.bug_id = bug_id
        self.reproduced = reproduced
        self.detail = detail

    def __str__(self) -> str:
        marker = "REPRODUCED" if self.reproduced else "ok        "
        return f"[{marker}] {self.bug_id}  {self.detail}"


def _create_user(first_name: str = "Night Shift") -> dict:
    response = requests.post(
        f"{API_URL}/users/create",
        json={
            "first_name": first_name,
            "last_name": "Doe",
            "email": f"{uuid.uuid4().hex[:12]}@example.com",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def trigger_b1() -> Outcome:
    """A user id that does not exist must come back as 404, never 500."""
    missing_id = randint(1_000_000, 9_999_999)
    response = requests.get(f"{API_URL}/users/{missing_id}", timeout=TIMEOUT)
    if response.status_code == 404:
        return Outcome("B1", False, f"GET /users/{missing_id} -> 404 as expected")
    return Outcome("B1", True, f"GET /users/{missing_id} -> {response.status_code} (expected 404)")


def trigger_b2() -> Outcome:
    """limit must cap the page size."""
    for index in range(3):
        _create_user(f"Pager{index}")
    response = requests.get(f"{API_URL}/users/", params={"limit": 2, "offset": 0}, timeout=TIMEOUT)
    if response.status_code != 200:
        return Outcome("B2", True, f"GET /users/?limit=2 -> {response.status_code} (expected 200)")
    count = len(response.json())
    if count == 2:
        return Outcome("B2", False, "GET /users/?limit=2 -> 2 users as expected")
    return Outcome("B2", True, f"GET /users/?limit=2 -> {count} users (expected 2); no ERROR log is written")


def trigger_b3() -> Outcome:
    """A status with zero logs must not divide by zero."""
    response = requests.get(f"{API_URL}/logs/stats", params={"status": "duplicate"}, timeout=TIMEOUT)
    if response.status_code == 200:
        return Outcome("B3", False, "GET /logs/stats?status=duplicate -> 200 as expected")
    return Outcome("B3", True, f"GET /logs/stats?status=duplicate -> {response.status_code} (expected 200)")


def trigger_b4() -> Outcome:
    """Deleting a user that really exists must succeed."""
    user = _create_user("Doomed")
    response = requests.delete(f"{API_URL}/users/{user['id']}", timeout=TIMEOUT)
    if response.status_code == 200:
        return Outcome("B4", False, f"DELETE /users/{user['id']} -> 200 as expected")
    return Outcome("B4", True, f"DELETE /users/{user['id']} -> {response.status_code} (expected 200)")


TRIGGERS = {"B1": trigger_b1, "B2": trigger_b2, "B3": trigger_b3, "B4": trigger_b4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--bug",
        default=os.getenv("FORCE_ERROR_BUG", "random"),
        help="B1, B2, B3, B4, or 'random' (default: $FORCE_ERROR_BUG or random)",
    )
    parser.add_argument("--all", action="store_true", help="run every trigger in order")
    args = parser.parse_args()

    if args.all:
        selected = list(TRIGGERS)
    elif args.bug.lower() == "random":
        selected = [list(TRIGGERS)[randint(0, len(TRIGGERS) - 1)]]
    else:
        bug_id = args.bug.strip().upper()
        if bug_id not in TRIGGERS:
            parser.error(f"unknown bug {args.bug!r}; choose from {', '.join(TRIGGERS)} or 'random'")
        selected = [bug_id]

    outcomes = []
    for bug_id in selected:
        try:
            outcome = TRIGGERS[bug_id]()
        except requests.RequestException as exc:
            outcome = Outcome(bug_id, True, f"request failed: {exc}")
        print(outcome, flush=True)
        outcomes.append(outcome)

    # Non-zero exit when a defect reproduced, so cron logs make it obvious.
    return 1 if any(outcome.reproduced for outcome in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
