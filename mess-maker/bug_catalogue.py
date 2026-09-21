"""Reproducible defects for the night-shift repair pipeline.

Each entry is a real, single-edit defect in `dummy-api-server`. A bug is
INJECTED by replacing `fixed` with `broken` in the named file, and REVERTED by
the opposite replacement. Both snippets must appear exactly once, so seeding is
deterministic and idempotent-checkable.

Adding a bug: write the `fixed` and `broken` snippets, a `trigger` (what the
mess-maker sends), and make sure `dummy-api-server/tests/test_api_contract.py`
has a test that fails ONLY while the bug is present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Bug:
    bug_id: str
    title: str
    file: str
    fixed: str
    broken: str
    symptom: str
    test: str
    # Whether triggering it over HTTP produces an ERROR log (and so a repair job).
    surfaces_in_logs: bool = True
    notes: str = ""


CATALOGUE: dict[str, Bug] = {}


def _register(bug: Bug) -> None:
    CATALOGUE[bug.bug_id] = bug


# --------------------------------------------------------------------------
# B1 - a missing user is serialised as null against a non-optional response
#      model, so FastAPI raises ResponseValidationError and returns 500.
# --------------------------------------------------------------------------
_register(Bug(
    bug_id="B1",
    title="Missing user returns 500 instead of 404",
    file="dummy-api-server/main.py",
    fixed='''    user = db.query(models.User).filter(models.User.id == id).first()
    if not user:
        # Expected condition, not a defect: log below ERROR so the repair
        # pipeline is not woken up for correct behaviour.
        logger.warning("Requested a non-existing user with id %s", id)
        raise HTTPException(status_code=404, detail=f"No user found with id {id}")
    write_application_log("INFO", f"Ran get user for id {id}")
    return user
''',
    broken='''    user = db.query(models.User).filter(models.User.id == id).first()
    write_application_log("INFO", f"Ran get user for id {id}")
    return user
''',
    symptom="GET /users/<unknown-id> -> 500 ResponseValidationError (expected 404)",
    test="test_unknown_user_returns_404",
))

# --------------------------------------------------------------------------
# B2 - limit and offset are swapped. No exception is raised: the endpoint
#      simply returns the wrong rows. Nothing reaches the error log.
# --------------------------------------------------------------------------
_register(Bug(
    bug_id="B2",
    title="Pagination limit and offset are swapped",
    file="dummy-api-server/main.py",
    fixed="    users = db.query(models.User).order_by(models.User.id).offset(offset).limit(limit).all()\n",
    broken="    users = db.query(models.User).order_by(models.User.id).offset(limit).limit(offset).all()\n",
    symptom="GET /users/?limit=2&offset=0 -> [] (expected 2 users)",
    test="test_pagination_respects_limit_and_offset",
    surfaces_in_logs=False,
    notes=(
        "Silent defect. Proves why REPAIR_VALIDATION_COMMAND must be a test "
        "suite: log-scraping alone can never detect this."
    ),
))

# --------------------------------------------------------------------------
# B3 - unguarded division by a count that is legitimately zero.
# --------------------------------------------------------------------------
_register(Bug(
    bug_id="B3",
    title="ZeroDivisionError in /logs/stats for an empty status",
    file="dummy-api-server/main.py",
    fixed='    share = counts.get("open", 0) / selected if selected else 0.0\n',
    broken='    share = counts.get("open", 0) / selected\n',
    symptom="GET /logs/stats?status=duplicate -> 500 ZeroDivisionError (expected 200)",
    test="test_log_stats_handles_empty_status",
))

# --------------------------------------------------------------------------
# B4 - string concatenation against an int path parameter.
# --------------------------------------------------------------------------
_register(Bug(
    bug_id="B4",
    title="TypeError concatenating str and int on successful delete",
    file="dummy-api-server/main.py",
    fixed='    write_application_log("INFO", f"Deleted user with id {id}")\n',
    broken='    write_application_log("INFO", "Deleted user with id " + id)\n',
    symptom="DELETE /users/<existing-id> -> 500 TypeError (expected 200)",
    test="test_delete_existing_user_succeeds",
))


def repo_root() -> Path:
    """The repository root, whether run from the host or from /app."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[1], Path("/source"), Path.cwd()):
        if (candidate / "dummy-api-server" / "main.py").exists():
            return candidate
    raise SystemExit("Could not locate the repository root (no dummy-api-server/main.py).")


def bug_state(bug: Bug, root: Path) -> str:
    """'seeded', 'clean', or 'unknown' for one bug."""
    text = (root / bug.file).read_text(encoding="utf-8")
    has_fixed = text.count(bug.fixed) == 1
    has_broken = text.count(bug.broken) == 1
    if has_fixed and not has_broken:
        return "clean"
    if has_broken and not has_fixed:
        return "seeded"
    return "unknown"
