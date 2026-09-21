# Reproducible bugs

The repair pipeline needs a defect it can actually find and verify. This is the
harness that provides one.

Three pieces:

| Piece | Path | Job |
|---|---|---|
| Catalogue | `mess-maker/bug_catalogue.py` | Defines each defect as a `fixed` ⇄ `broken` snippet pair |
| Seeder | `mess-maker/seed_bugs.py` | Injects / reverts a defect on demand |
| Contract suite | `dummy-api-server/tests/test_api_contract.py` | Fails while a defect is present, passes once fixed |

The committed source is **clean**. Bugs are injected, never committed, so you
can run the same demo as many times as you like.

---

## The four defects

| ID | Defect | Symptom | Reaches Redis? |
|---|---|---|---|
| **B1** | Missing user serialised against a non-optional response model | `GET /users/<unknown>` → 500 `ResponseValidationError` (expected 404) | yes |
| **B2** | `limit` and `offset` swapped | `GET /users/?limit=2` → `[]` (expected 2 users) | **no** |
| **B3** | Unguarded division by a zero count | `GET /logs/stats?status=duplicate` → 500 `ZeroDivisionError` | yes |
| **B4** | `str + int` on a path parameter | `DELETE /users/<existing>` → 500 `TypeError` | yes |

**B2 is the important one.** It raises nothing, so no ERROR log is written and
the worker is never woken up — yet the endpoint is plainly wrong. It is the
reason `REPAIR_VALIDATION_COMMAND` must be a test suite rather than a `/health`
probe or a log scrape.

Each defect fails **exactly one** test, so the failure names the fix.

---

## Running it

```bash
# what is currently broken
python mess-maker/seed_bugs.py --status

# break something
python mess-maker/seed_bugs.py --seed B1        # one
python mess-maker/seed_bugs.py --seed B1,B3     # several
python mess-maker/seed_bugs.py --seed random    # surprise me
python mess-maker/seed_bugs.py --seed all

# rebuild so the change is live
docker compose up -d --build fastapi

# confirm it reproduces, two ways
docker compose exec fastapi python -m pytest -q tests/test_api_contract.py
docker compose run --rm error-generator python force-error.py --bug B1

# let the night-shift worker try
docker compose --profile worker up -d worker
docker compose logs -f worker

# put it back
python mess-maker/seed_bugs.py --revert all
```

Seeding is idempotent and verifies each snippet appears exactly once before
touching the file. If the source has drifted from the catalogue, it refuses
rather than corrupting anything.

---

## What changed in the app, and why

**Expected 4xx no longer logs at ERROR.** `GET`/`DELETE` on a missing user now
log at WARNING. Previously a 404 — correct behaviour — enqueued a repair job,
so the pipeline spent every cycle on work that had nothing to fix.

**Unhandled exceptions now reach Redis.** A new `@app.exception_handler(Exception)`
routes any unhandled failure through `report_exception`. Without it, B1 and B3
returned 500 to the caller and wrote *nothing* to Redis — verified: four
triggered 500s produced zero queued repair jobs. `HTTPException` is deliberately
excluded, so expected 4xx stays out of the queue.

The error records the worker now receives carry the real exception type and
location:

```
ResponseValidationError: ... at GET /users/3009089
ZeroDivisionError: division by zero at GET /logs/stats
TypeError: can only concatenate str (not "int") to str at DELETE /users/71
```

**`REPAIR_VALIDATION_COMMAND` now defaults to the contract suite:**

```
python -m pytest -q --no-header -p no:cacheprovider tests/test_api_contract.py
```

**Docker tool errors now include stdout.** pytest reports failures on stdout;
the tool captured only stderr, so a failing suite reached the model as
`exit status 1` with no detail.

**New endpoints** (`GET /users/` with pagination, `GET /logs/stats`) exist to
host B2 and B3. `UserRead` was added so read endpoints expose `id`.

---

## Adding a bug

1. Add a `Bug(...)` to `mess-maker/bug_catalogue.py`. The `fixed` and `broken`
   snippets must each appear exactly once in the file and end at a line
   boundary, so neither is a prefix of the other.
2. Add one test to `dummy-api-server/tests/test_api_contract.py` that fails only
   while that bug is present.
3. Add a `trigger_*` function to `mess-maker/force-error.py` and register it in
   `TRIGGERS`.
4. `night-shift-worker-agent/tests/test_seeded_bug_roundtrip.py` picks it up
   automatically and will fail if the snippets have drifted.

Keep new tests independent of the endpoints other bugs break — otherwise one
defect cascades into several failures and the signal stops naming the fix.
