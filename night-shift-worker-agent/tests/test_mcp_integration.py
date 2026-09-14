import os
import tempfile
from pathlib import Path

from tools.mcp_registry import MCPRegistry
from main import RepairWorker, WorkerRedisClient


def test_worker_exposes_mcp_registry(tmp_path):
    registry = MCPRegistry(str(tmp_path))
    workspace = registry.call("create_workspace", guid="repair-123")
    assert Path(workspace).exists()

    worker = RepairWorker(redis_client=WorkerRedisClient(host="127.0.0.1", port=6379, db=0), registry=registry)
    assert hasattr(worker, "mcp_registry")
    assert worker.mcp_registry is registry
