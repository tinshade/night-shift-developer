import os
from uuid import uuid4
from redis import Redis
from redis.exceptions import ResponseError
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, cast


class LogManager:

    def __init__(self):
        self.redis_client: Redis = Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
        )
        self.stream_name = "logs:error"
        self.group_name = "handlers"
        self.ensure_consumer_group()

    def ensure_consumer_group(self):
        try:
            self.redis_client.xgroup_create(
                self.stream_name,
                self.group_name,
                id="$",
                mkstream=True,
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def write_log(
        self,
        log_type: str,
        application_name: str,
        message: str,
        trace: str = "",
        status: str = "open",
    ):
        guid = str(uuid4())
        record: dict[str, str] = {
            "guid": guid,
            "datetime": datetime.now(timezone.utc).isoformat(),
            "type": log_type,
            "status": status,
            "application": application_name,
            "message": message,
            "trace": trace
        }

        pipeline = self.redis_client.pipeline()
        pipeline.hset(f"log:{guid}", mapping=cast(Mapping[Any, Any], record))
        pipeline.sadd(f"logs:status:{status}", guid)
        if log_type.lower() == "error" and status == "open":
            pipeline.xadd(self.stream_name, {"guid": guid}, maxlen=100_000, approximate=True)
        pipeline.execute()
        return guid

    def get_log(self, guid: str):
        record = self.redis_client.hgetall(f"log:{guid}")
        return record or None

    def set_status(self, guid: str, new_status: str):
        old = self.redis_client.hget(f"log:{guid}", "status")
        if old is None:
            return False
        pipe = self.redis_client.pipeline()
        pipe.hset(f"log:{guid}", "status", new_status)
        pipe.smove(f"logs:status:{old}", f"logs:status:{new_status}", guid)
        pipe.execute()
        return True

    def consume(self, func: Callable[[str, dict[str, str]], str], consumer_name: str = "worker-1"):
        while True:
            resp = cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], self.redis_client.xreadgroup(
                self.group_name,
                consumer_name,
                {self.stream_name: ">"},
                count=10,
                block=1_000,
            ))
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    guid = fields["guid"]
                    record = cast(dict[str, str], self.redis_client.hgetall(f"log:{guid}"))

                    self.set_status(guid, "in_progress")
                    try:
                        result = func(guid, record)
                        self.set_status(guid, result or "fixed")
                    except Exception:
                        self.set_status(guid, "wontfix")

                    self.redis_client.xack(self.stream_name, self.group_name, entry_id)


    def recover(self, consumer_name:str="worker-1", idle_ms:int=60_000):
        cursor = "0-0"
        while True:
            cursor, entries, _ = self.redis_client.xautoclaim(
                self.stream_name,
                self.group_name,
                consumer_name,
                idle_ms,
                start_id=cursor,
                count=10,
            )
            for entry_id, fields in entries:
                ...  # same handling
            if cursor == "0-0":
                break