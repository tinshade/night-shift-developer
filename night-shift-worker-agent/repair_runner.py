from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import shlex
import logging
from typing import Any

from tools.docker_mcp import DockerContainerSpec
from tools.base import ToolError

logger = logging.getLogger("night-shift-repair-runner")


@dataclass
class RepairDiagnostics:
    passed: bool
    output: str
    tests_run: list[str] = field(default_factory=list)
    cleanup_ok: bool = True
    cleanup_error: str = ""


class IsolatedRepairRunner:
    """Run one repair validation attempt using resources named for one GUID."""

    def __init__(self, registry: Any, timeout_seconds: int = 600):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    def run(self, guid: str, source_path: str) -> RepairDiagnostics:
        logger.info("Starting isolated repair guid=%s source=%s", guid, source_path)
        prefix = f"repair_{guid}"
        image = f"{prefix}:latest"
        network = f"{prefix}_network"
        postgres_volume = f"{prefix}_postgres"
        redis_volume = f"{prefix}_redis"
        containers = [f"{prefix}_postgres", f"{prefix}_redis", f"{prefix}_api"]
        output: list[str] = []
        cleanup_errors: list[str] = []
        passed = False
        try:
            api_source = Path(source_path) / "dummy-api-server"
            dockerfile = api_source / "Dockerfile"
            build_context = api_source if dockerfile.exists() else Path(source_path)
            self.registry.call("build_image", context=str(build_context), dockerfile=str(dockerfile) if dockerfile.exists() else None, tag=image)
            logger.info("Built repair image=%s", image)
            self.registry.call("create_network", name=network)
            self.registry.call("create_volume", name=postgres_volume)
            self.registry.call("create_volume", name=redis_volume)
            self.registry.call(
                "create_container",
                spec=DockerContainerSpec(
                    image="postgres:16",
                    name=containers[0],
                    network=network,
                    env={"POSTGRES_USER": "repair", "POSTGRES_PASSWORD": "repair", "POSTGRES_DB": "repair"},
                    volumes=[f"{postgres_volume}:/var/lib/postgresql/data"],
                    healthcheck="CMD-SHELL pg_isready -U repair -d repair",
                ),
            )
            self.registry.call(
                "create_container",
                spec=DockerContainerSpec(
                    image="redis:7-alpine",
                    name=containers[1],
                    network=network,
                    volumes=[f"{redis_volume}:/data"],
                    command=["redis-server", "--appendonly", "yes"],
                    healthcheck="CMD redis-cli ping",
                ),
            )
            self.registry.call(
                "create_container",
                spec=DockerContainerSpec(
                    image=image,
                    name=containers[2],
                    network=network,
                    env={
                        "POSTGRES_HOST": containers[0],
                        "POSTGRES_PORT": "5432",
                        "POSTGRES_USER": "repair",
                        "POSTGRES_PASSWORD": "repair",
                        "POSTGRES_DB": "repair",
                        "REDIS_HOST": containers[1],
                        "REDIS_PORT": "6379",
                    },
                    # NOTE: no bind mount here. The worker runs in a container and
                    # talks to the HOST docker daemon, so a host bind mount of
                    # /workspaces/<guid>/... would resolve to a non-existent host
                    # path and silently mount an empty directory over /app.
                    # build_image already baked the patched source into the image.
                    command=[],
                    healthcheck="CMD-SHELL python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')\"",
                ),
            )
            for container in containers[:2]:
                self.registry.call("start_container", container_id=container)
            for container in containers[:2]:
                if not self.registry.call("wait_for_health", container_id=container, timeout_seconds=60):
                    raise ToolError(f"Repair container did not become ready: {container}")
            self.registry.call("start_container", container_id=containers[2])
            if not self.registry.call("wait_for_health", container_id=containers[2], timeout_seconds=60):
                raise ToolError(f"Repair container did not become ready: {containers[2]}")
            logger.info("Repair services healthy guid=%s", guid)
            # The validation command MUST exercise the reported defect. A bare
            # /health probe can go green while the bug is untouched.
            validation_command = os.getenv(
                "REPAIR_VALIDATION_COMMAND",
                "python -m pytest -q --no-header -p no:cacheprovider tests/test_api_contract.py",
            )
            health = self.registry.call(
                "exec_command",
                container_id=containers[2],
                command=shlex.split(validation_command),
            )
            output.append(health)
            for container in containers:
                output.append(f"[{container}]\n{self.registry.call('read_logs', container_id=container)}")
            passed = True
            logger.info("Repair validation passed guid=%s", guid)
        except Exception as exc:
            logger.exception("Repair validation failed guid=%s", guid)
            output.append(str(exc))
            for container in containers:
                try:
                    output.append(f"[{container}]\n{self.registry.call('read_logs', container_id=container)}")
                except Exception as log_error:
                    output.append(f"[{container}] {log_error}")
        finally:
            for container in reversed(containers):
                try:
                    self.registry.call("stop_container", container_id=container)
                except Exception as exc:
                    cleanup_errors.append(f"stop {container}: {exc}")
                try:
                    self.registry.call("remove_container", container_id=container)
                except Exception as exc:
                    cleanup_errors.append(f"remove {container}: {exc}")
            for resource, tool_name in ((network, "remove_network"), (postgres_volume, "remove_volume"), (redis_volume, "remove_volume")):
                try:
                    self.registry.call(tool_name, **({"name": resource}))
                except Exception as exc:
                    cleanup_errors.append(f"{tool_name} {resource}: {exc}")
            try:
                self.registry.call("remove_image", image=image)
            except Exception as exc:
                cleanup_errors.append(f"remove_image {image}: {exc}")
        return RepairDiagnostics(
            passed=passed,
            output="\n".join(output),
            tests_run=[os.getenv("REPAIR_VALIDATION_COMMAND", "pytest tests/test_api_contract.py")],
            cleanup_ok=not cleanup_errors,
            cleanup_error="\n".join(cleanup_errors),
        )
