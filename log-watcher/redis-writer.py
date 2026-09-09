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