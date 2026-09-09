Redis is a good fit, but one property will trip you up immediately: stream entries are immutable. You can XADD and XDEL, but there is no operation to change a field inside an entry that's already in a stream. Your status field needs to move through open → processing → fixed, so it cannot live in the stream.

The fix is to split the two jobs that you're currently imagining as one record:

Stream = transport. Immutable, append-only, blocking reads, consumer groups. This is what wakes your function up.
Hash = state. Keyed by your guid, holds the record, and HSET mutates status as many times as you like.

The stream entry just carries the guid. The hash is the single source of truth.

Key layout
logs:error              stream    notification channel (errors only)
log:{guid}              hash      the full record, mutable status
logs:status:{status}    set       index, so you can query "all open errors"

Route at write time rather than pushing every log into one stream and filtering — Redis has no server-side filtering, so a single stream means your consumer wakes for every DEBUG line too.

Writer
python
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

The pipeline sends all commands in one round trip and executes them as a transaction, so you can't end up with a stream entry pointing at a hash that doesn't exist yet.

I'd change your datetime format. "09/17/2026-15:17:48" doesn't sort lexicographically, is ambiguous between US and international readers, and carries no timezone. ISO 8601 sorts correctly as a plain string and parses everywhere. You also get time ordering for free regardless — Redis stream IDs are {unix_ms}-{seq}.

Consumer
python
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

block=0 blocks indefinitely until an error arrives. No polling loop, no sleep, no wasted round trips.

Consumer groups also give you the "seen" tracking you described, for free. When XREADGROUP hands you an entry it goes into the group's pending list; XACK removes it. If your worker crashes mid-handling, the entry stays pending and another worker can claim it:

python
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

Run that on startup and periodically. It's the piece that makes the difference between "usually works" and "survives a restart."

On latency

XADD over loopback is well under a millisecond, but it's still a synchronous round trip on your request path. If you're logging inside a hot handler, push onto a queue.Queue and let a background thread drain it with pipelined writes. That takes the database entirely off the critical path, at the cost of losing whatever's buffered if the process dies hard.

Also check your persistence settings. Redis defaults to RDB snapshots, which can lose the last several minutes on a crash. For logs you likely want AOF with appendfsync everysec — bounded loss of about one second, minimal throughput cost.

One last thing: MAXLEN trims the stream, but the hashes and status sets grow forever. Decide early whether resolved records get a TTL, get archived to disk, or stay — it's much easier to build that in now than to retrofit it once you have millions of keys.