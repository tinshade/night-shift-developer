import json, uuid, time
from datetime import datetime, timezone
import redis

r = redis.Redis(decode_responses=True)

def write_log(type_, application, message, trace=""):
    guid = str(uuid.uuid4())
    record = {
        "guid": guid,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "type": type_,
        "status": "open",
        "application": application,
        "message": message,
        "trace": trace,
    }

    pipe = r.pipeline()
    pipe.hset(f"log:{guid}", mapping=record)
    if type_ == "ERROR":
        pipe.sadd("logs:status:open", guid)
        pipe.xadd("logs:error", {"guid": guid}, maxlen=100_000, approximate=True)
    pipe.execute()
    return guid

r.xgroup_create("logs:error", "handlers", id="$", mkstream=True)  # once, ignore BUSYGROUP

def set_status(guid, new_status):
    old = r.hget(f"log:{guid}", "status")
    pipe = r.pipeline()
    pipe.hset(f"log:{guid}", "status", new_status)
    pipe.smove("logs:status:" + old, "logs:status:" + new_status, guid)
    pipe.execute()

def consume(consumer_name="worker-1"):
    while True:
        resp = r.xreadgroup("handlers", consumer_name,
                            {"logs:error": ">"}, count=10, block=0)
        for _stream, entries in resp:
            for entry_id, fields in entries:
                guid = fields["guid"]
                record = r.hgetall(f"log:{guid}")

                set_status(guid, "processing")
                try:
                    result = my_custom_function(record)
                    set_status(guid, result)      # "fixed" | "broken" | "wontfix"
                except Exception:
                    set_status(guid, "broken")

                r.xack("logs:error", "handlers", entry_id)


def recover(consumer_name="worker-1", idle_ms=60_000):
    cursor = "0-0"
    while True:
        cursor, entries, _ = r.xautoclaim(
            "logs:error", "handlers", consumer_name, idle_ms, start_id=cursor, count=10
        )
        for entry_id, fields in entries:
            ...  # same handling
        if cursor == "0-0":
            break