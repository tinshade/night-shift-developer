import sys
from pathlib import Path

import fakeredis

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.redis.log_manager import LogManager, RepairResult


def make_manager():
    return LogManager(redis_client=fakeredis.FakeRedis(decode_responses=True))


def test_primary_error_claims_and_duplicates_are_recorded():
    manager = make_manager()

    primary_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")
    duplicate_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")

    primary = manager.get_log(primary_guid)
    duplicate = manager.get_log(duplicate_guid)
    fingerprint = primary["error_fingerprint"]

    assert primary["status"] == "open"
    assert duplicate["status"] == "duplicate"
    assert duplicate["duplicate_of"] == primary_guid
    assert duplicate["error_fingerprint"] == fingerprint
    assert manager.redis_client.xlen("logs:all") >= 2
    assert manager.redis_client.xlen("logs:errors") == 1
    assert manager.redis_client.xrange("logs:errors")[-1][1]["guid"] == primary_guid
    assert manager.redis_client.get(f"repair:active:{fingerprint}") == primary_guid


def test_status_transitions_create_cooldown_and_block_repeats():
    manager = make_manager()

    primary_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")
    fingerprint = manager.get_log(primary_guid)["error_fingerprint"]

    assert manager.set_status(primary_guid, "in_progress") is True
    assert manager.set_status(primary_guid, "fixed") is True

    assert manager.redis_client.exists(f"repair:active:{fingerprint}") == 0
    assert manager.redis_client.get(f"repair:cooldown:{fingerprint}") == primary_guid
    assert manager.redis_client.ttl(f"repair:cooldown:{fingerprint}") > 0

    repeat_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")
    assert manager.get_log(repeat_guid)["status"] == "duplicate"
    assert manager.redis_client.xlen("logs:errors") == 1


def test_worker_processes_only_open_error_records_and_marks_wontfix_on_failure():
    manager = make_manager()
    worker = manager.worker()

    primary_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")
    result = worker.process_guid(primary_guid, lambda guid, record: "fixed")

    assert isinstance(result, RepairResult)
    assert result.status == "fixed"
    assert manager.get_log(primary_guid)["status"] == "fixed"

    duplicate_guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")
    result = worker.process_guid(duplicate_guid, lambda guid, record: "fixed")
    assert result.status == "duplicate"
    assert result.summary == "Duplicate record skipped."

    failure_guid = manager.write_log("ERROR", "orders-api", "RuntimeError: fail", "Traceback...")
    result = worker.process_guid(failure_guid, lambda guid, record: (_ for _ in ()).throw(RuntimeError("oops")))
    assert result.status == "wontfix"
    assert manager.get_log(failure_guid)["status"] == "wontfix"


def test_worker_recover_handles_pending_error_entries_idempotently():
    manager = make_manager()
    guid = manager.write_log("ERROR", "orders-api", "ValueError: boom", "Traceback...")

    manager.redis_client.xreadgroup(
        "repair-workers",
        "stale-worker",
        {"logs:errors": ">"},
        count=10,
        block=0,
    )
    manager.set_status(guid, "in_progress")

    manager.worker("recover-1").recover(lambda guid, record: "fixed", consumer_name="recover-1", idle_ms=0)

    assert manager.get_log(guid)["status"] == "fixed"
    pending = manager.redis_client.xpending("logs:errors", "repair-workers")
    assert pending["pending"] == 0
    assert pending["consumers"] == []
