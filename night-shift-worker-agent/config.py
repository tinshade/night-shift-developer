import os

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REPAIR_DEDUPE_TTL_SECONDS = int(os.getenv("REPAIR_DEDUPE_TTL_SECONDS", "3600"))
ERROR_STREAM = "logs:errors"
ERROR_GROUP = "repair-workers"
STATUS_PREFIX = "logs:status:"
ACTIVE_PREFIX = "repair:active:"
COOLDOWN_PREFIX = "repair:cooldown:"
