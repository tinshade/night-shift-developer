import logging
import os
from dataclasses import dataclass, field
from typing import Callable

import redis

from config import (
    ACTIVE_PREFIX,
    COOLDOWN_PREFIX,
    ERROR_GROUP,
    ERROR_STREAM,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PORT,
    REPAIR_DEDUPE_TTL_SECONDS,
    STATUS_PREFIX,
)
from repair_workflow import RepairWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("night-shift-worker")


@dataclass
class RepairResult:
    status: str
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    remaining_error: str = ""


class WorkerRedisClient:
    def __init__(self, host: str = REDIS_HOST, port: int = REDIS_PORT, db: int = REDIS_DB):
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.ensure_group()

    def ensure_group(self):
        try:
            self.client.xgroup_create(ERROR_STREAM, ERROR_GROUP, id="$", mkstream=True)
        except redis.exceptions.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def get_log(self, guid: str):
        return self.client.hgetall(f"log:{guid}") or None

    def set_status(self, guid: str, new_status: str):
        existing = self.client.hget(f"log:{guid}", "status")
        if existing is None:
            return False
        if existing == new_status:
            return True

        fingerprint = self.client.hget(f"log:{guid}", "error_fingerprint")
        with self.client.pipeline() as pipe:
            pipe.hset(f"log:{guid}", "status", new_status)
            if existing:
                pipe.srem(f"{STATUS_PREFIX}{existing}", guid)
            pipe.sadd(f"{STATUS_PREFIX}{new_status}", guid)
            if new_status in {"fixed", "wontfix"} and fingerprint:
                pipe.delete(f"{ACTIVE_PREFIX}{fingerprint}")
                pipe.set(f"{COOLDOWN_PREFIX}{fingerprint}", guid, ex=REPAIR_DEDUPE_TTL_SECONDS)
            pipe.execute()
        return True

    def update_metadata(self, guid: str, **metadata):
        if not metadata:
            return
        self.client.hset(f"log:{guid}", mapping=metadata)

    def ack(self, entry_id: str):
        self.client.xack(ERROR_STREAM, ERROR_GROUP, entry_id)


class RepairWorker:
    def __init__(self, redis_client: WorkerRedisClient, registry=None):
        self.redis = redis_client
        self.mcp_registry = registry

    def process_guid(self, guid: str, repair_handler: Callable[[str, dict], str | None]):
        record = self.redis.get_log(guid)
        if not record:
            return RepairResult(status="wontfix", summary="No log record found for the GUID.")

        if record.get("status") != "open":
            return RepairResult(status=record.get("status", "duplicate"), summary="Duplicate record skipped.")

        fingerprint = record.get("error_fingerprint")
        if fingerprint:
            active_guid = self.redis.client.get(f"{ACTIVE_PREFIX}{fingerprint}")
            if active_guid != guid:
                self.redis.set_status(guid, "duplicate")
                self.redis.update_metadata(guid, duplicate_of=active_guid or "")
                return RepairResult(status="duplicate", summary="Repair claim no longer belonged to this GUID.")

        self.redis.set_status(guid, "in_progress")
        try:
            result = repair_handler(guid, record)
            final_status = result or "fixed"
            if final_status not in {"fixed", "wontfix"}:
                final_status = "fixed"
            self.redis.set_status(guid, final_status)
            return RepairResult(status=final_status, summary=f"Repair completed with status {final_status}.")
        except Exception as exc:
            self.redis.set_status(guid, "wontfix")
            self.redis.update_metadata(guid, repair_error=str(exc), repair_summary=f"Unexpected failure: {exc}")
            return RepairResult(status="wontfix", summary=f"Unexpected failure: {exc}")

    def consume(self, repair_handler: Callable[[str, dict], str | None], block_ms: int = 1000, count: int = 10):
        while True:
            response = self.redis.client.xreadgroup(
                ERROR_GROUP,
                "worker-1",
                {ERROR_STREAM: ">"},
                count=count,
                block=block_ms,
            )
            if not response:
                continue

            for _stream, entries in response:
                for entry_id, fields in entries:
                    guid = fields.get("guid")
                    if not guid:
                        self.redis.ack(entry_id)
                        continue

                    record = self.redis.get_log(guid)
                    if record is None:
                        self.redis.ack(entry_id)
                        continue

                    if record.get("status") != "open":
                        self.redis.ack(entry_id)
                        continue

                    result = self.process_guid(guid, repair_handler)
                    self.redis.ack(entry_id)
                    logger.info("Processed guid=%s status=%s summary=%s", guid, result.status, result.summary)


if __name__ == "__main__":
    from tools.mcp_registry import MCPRegistry

    redis_client = WorkerRedisClient()
    registry = MCPRegistry("/workspaces")
    worker = RepairWorker(redis_client, registry=registry)
    source_repository = os.getenv("REPAIR_SOURCE_REPOSITORY")
    workflow = RepairWorkflow("/workspaces", registry=registry)

    def repair_handler(guid: str, record: dict):
        if not source_repository:
            raise RuntimeError("REPAIR_SOURCE_REPOSITORY is required for repair execution.")
        result = workflow.run(guid, source_repository, record=record)
        redis_client.update_metadata(
            guid,
            repair_summary=result.summary,
            repair_error=result.remaining_error,
            pr_url=result.pr_url,
            repair_tests_run=", ".join(result.tests_run),
        )
        return result.status

    logger.info("Starting Redis repair worker for %s", ERROR_STREAM)
    worker.consume(repair_handler)
