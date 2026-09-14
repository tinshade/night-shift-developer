import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, cast
from uuid import uuid4

from redis import Redis
from redis.exceptions import ResponseError


@dataclass
class RepairResult:
    status: str
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    remaining_error: str = ""


class RepairWorker:
    def __init__(self, log_manager: "LogManager", group_name: str = "repair-workers", consumer_name: str = "worker-1"):
        self.log_manager = log_manager
        self.group_name = group_name
        self.consumer_name = consumer_name

    def process_guid(self, guid: str, handler: Callable[[str, dict[str, str]], str | None]):
        record = self.log_manager.get_log(guid)
        if record is None:
            return RepairResult(status="wontfix", summary="No log record found for the GUID.")

        status = record.get("status")
        if status not in {"open", "in_progress"}:
            return RepairResult(status=status or "duplicate", summary="Duplicate record skipped.")

        fingerprint = record.get("error_fingerprint")
        active_guid = None if not fingerprint else self.log_manager.redis_client.get(f"repair:active:{fingerprint}")
        if active_guid != guid and status == "open":
            self.log_manager.set_status(guid, "duplicate")
            self.log_manager.update_repair_metadata(guid, duplicate_of=active_guid or "")
            return RepairResult(status="duplicate", summary="Repair claim no longer belonged to this GUID.")

        if status == "open":
            self.log_manager.set_status(guid, "in_progress")
        try:
            result = handler(guid, record)
            final_status = result or "fixed"
            if final_status not in {"fixed", "wontfix"}:
                final_status = "fixed"
            self.log_manager.set_status(guid, final_status)
            return RepairResult(status=final_status, summary=f"Repair completed with status {final_status}.")
        except Exception as exc:
            self.log_manager.set_status(guid, "wontfix")
            self.log_manager.update_repair_metadata(guid, repair_error=str(exc), repair_summary=f"Unexpected failure: {exc}")
            return RepairResult(status="wontfix", summary=f"Unexpected failure: {exc}")

    def consume(self, handler: Callable[[str, dict[str, str]], str | None], block_ms: int = 1000, count: int = 10):
        while True:
            response = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                self.log_manager.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {self.log_manager.error_stream_name: ">"},
                    count=count,
                    block=block_ms,
                ),
            )
            if not response:
                continue

            for _stream, entries in response:
                for entry_id, fields in entries:
                    guid = fields.get("guid")
                    if not guid:
                        self.log_manager.redis_client.xack(self.log_manager.error_stream_name, self.group_name, entry_id)
                        continue

                    record = self.log_manager.get_log(guid)
                    if record is None:
                        self.log_manager.redis_client.xack(self.log_manager.error_stream_name, self.group_name, entry_id)
                        continue

                    if record.get("status") != "open":
                        self.log_manager.redis_client.xack(self.log_manager.error_stream_name, self.group_name, entry_id)
                        continue

                    result = self.process_guid(guid, handler)
                    self.log_manager.redis_client.xack(self.log_manager.error_stream_name, self.group_name, entry_id)
                    if result.status in {"fixed", "wontfix"}:
                        continue

    def recover(
        self,
        handler: Callable[[str, dict[str, str]], str | None] | None = None,
        consumer_name: str | None = None,
        idle_ms: int = 60_000,
    ):
        consumer_name = consumer_name or self.consumer_name
        handler = handler or (lambda _guid, _record: "fixed")
        cursor = "0-0"
        while True:
            cursor, entries, _ = self.log_manager.redis_client.xautoclaim(
                self.log_manager.error_stream_name,
                self.group_name,
                consumer_name,
                idle_ms,
                start_id=cursor,
                count=10,
            )
            for entry_id, fields in entries:
                guid = fields.get("guid")
                if guid:
                    self.process_guid(guid, handler)
                    self.log_manager.redis_client.xack(self.log_manager.error_stream_name, self.group_name, entry_id)
            if cursor == "0-0":
                break


class LogManager:
    def __init__(self, redis_client: Redis | None = None):
        self.redis_client: Redis = redis_client or Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
        )
        self.all_stream_name = "logs:all"
        self.error_stream_name = "logs:errors"
        self.all_group_name = "log-maintainers"
        self.error_group_name = "repair-workers"
        self.repair_dedupe_ttl_seconds = int(os.getenv("REPAIR_DEDUPE_TTL_SECONDS", "3600"))
        self.ensure_consumer_groups()

    def ensure_consumer_groups(self):
        for stream_name, group_name in ((self.all_stream_name, self.all_group_name), (self.error_stream_name, self.error_group_name)):
            try:
                self.redis_client.xgroup_create(stream_name, group_name, id="$", mkstream=True)
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise

    def _status_key(self, status: str) -> str:
        return f"logs:status:{status}"

    def _repair_active_key(self, fingerprint: str) -> str:
        return f"repair:active:{fingerprint}"

    def _repair_cooldown_key(self, fingerprint: str) -> str:
        return f"repair:cooldown:{fingerprint}"

    def normalize_error_identity(self, application_name: str, exception_type: str, message: str, trace: str) -> str:
        normalized = f"{application_name}\n{exception_type}\n{message}\n{trace}"
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\\", "/")
        normalized = re.sub(r"[A-Za-z]:/", "/", normalized)
        normalized = re.sub(r"(?i)0x[0-9a-f]+", "<memory>", normalized)
        normalized = re.sub(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
            "<uuid>",
            normalized,
        )
        normalized = re.sub(
            r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b",
            "<timestamp>",
            normalized,
        )
        normalized = re.sub(
            r"(?i)((?:request[_-]?id|trace[_-]?id|correlation[_-]?id|session[_-]?id|x-request-id))[=: ]+[A-Za-z0-9-]+",
            lambda match: f"{match.group(1)}=<id>",
            normalized,
        )
        normalized = re.sub(
            r"(?i)(?:port|pid|duration|elapsed|timeout|http_status|status_code)[=: ]+\d+",
            lambda match: match.group(0).split("=", 1)[0] + "=<number>",
            normalized,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def generate_error_fingerprint(self, application_name: str, exception_type: str, message: str, trace: str) -> str:
        identity = self.normalize_error_identity(application_name, exception_type, message, trace)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def write_log(
        self,
        log_type: str,
        application_name: str,
        message: str,
        trace: str = "",
        status: str = "open",
    ):
        guid = str(uuid4())
        error_fingerprint = ""
        duplicate_of = ""
        if log_type.lower() == "error":
            exception_type = message.split(":", 1)[0] if ":" in message else "UNKNOWN"
            error_fingerprint = self.generate_error_fingerprint(application_name, exception_type, message, trace)
            cooldown_guid = self.redis_client.get(f"repair:cooldown:{error_fingerprint}")
            if cooldown_guid:
                status = "duplicate"
                duplicate_of = cooldown_guid
            else:
                active_guid = self.redis_client.get(f"repair:active:{error_fingerprint}")
                if active_guid is None:
                    claim_set = self.redis_client.set(f"repair:active:{error_fingerprint}", guid, nx=True, ex=self.repair_dedupe_ttl_seconds)
                    if not claim_set:
                        active_guid = self.redis_client.get(f"repair:active:{error_fingerprint}")
                if active_guid is None or active_guid == guid:
                    status = "open"
                else:
                    status = "duplicate"
                    duplicate_of = active_guid

        record: dict[str, str] = {
            "guid": guid,
            "datetime": datetime.now(timezone.utc).isoformat(),
            "type": log_type,
            "status": status,
            "application": application_name,
            "message": message,
            "trace": trace,
        }
        if error_fingerprint:
            record["error_fingerprint"] = error_fingerprint
        if duplicate_of:
            record["duplicate_of"] = duplicate_of

        pipeline = self.redis_client.pipeline()
        pipeline.hset(f"log:{guid}", mapping=cast(Mapping[Any, Any], record))
        pipeline.sadd(self._status_key(status), guid)
        pipeline.xadd(self.all_stream_name, {"guid": guid}, maxlen=100_000, approximate=True)
        if log_type.lower() == "error" and status == "open":
            pipeline.xadd(self.error_stream_name, {"guid": guid}, maxlen=100_000, approximate=True)
        pipeline.execute()
        return guid

    def get_log(self, guid: str):
        record = self.redis_client.hgetall(f"log:{guid}")
        return record or None

    def set_status(self, guid: str, new_status: str):
        old = self.redis_client.hget(f"log:{guid}", "status")
        if old is None:
            return False
        if old == new_status:
            return True

        fingerprint = self.redis_client.hget(f"log:{guid}", "error_fingerprint")
        pipe = self.redis_client.pipeline()
        pipe.hset(f"log:{guid}", "status", new_status)
        if old:
            pipe.srem(self._status_key(old), guid)
        pipe.sadd(self._status_key(new_status), guid)

        if new_status in {"fixed", "wontfix"} and fingerprint:
            pipe.delete(self._repair_active_key(fingerprint))
            pipe.set(self._repair_cooldown_key(fingerprint), guid, ex=self.repair_dedupe_ttl_seconds)
        pipe.execute()
        return True

    def update_repair_metadata(self, guid: str, **metadata: str):
        if not metadata:
            return
        self.redis_client.hset(f"log:{guid}", mapping=cast(Mapping[Any, Any], metadata))

    def worker(self, consumer_name: str = "worker-1"):
        return RepairWorker(self, group_name=self.error_group_name, consumer_name=consumer_name)

    def consume(self, func: Callable[[str, dict[str, str]], str | None], consumer_name: str = "worker-1"):
        self.worker(consumer_name).consume(func)

    def recover(
        self,
        func: Callable[[str, dict[str, str]], str | None] | None = None,
        consumer_name: str = "worker-1",
        idle_ms: int = 60_000,
    ):
        self.worker(consumer_name).recover(func, consumer_name=consumer_name, idle_ms=idle_ms)
