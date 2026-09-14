from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
import time

from .base import MCPTool, ToolError, ToolRegistry


@dataclass
class DockerContainerSpec:
    image: str
    name: str
    env: dict[str, str] | None = None
    ports: dict[str, str] | None = None
    volumes: list[str] | None = None
    command: list[str] | None = None
    network: str | None = None
    healthcheck: str | None = None


class DockerMCP:
    """Narrow Docker adapter used by the repair workflow."""

    def __init__(self, project_prefix: str = "repair"):
        self.project_prefix = project_prefix
        self.command_timeout = int(os.getenv("REPAIR_COMMAND_TIMEOUT_SECONDS", "120"))

    def _run(self, args: list[str], timeout: int | None = None) -> str:
        try:
            completed = subprocess.run(
                ["docker", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout or self.command_timeout,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise ToolError(f"Docker operation failed: {detail}") from exc
        return completed.stdout.strip()

    def build_image(self, context: str, dockerfile: str | None = None, tag: str | None = None) -> str:
        image = tag or f"{self.project_prefix}:latest"
        args = ["build", "--tag", image]
        if dockerfile:
            args.extend(["--file", dockerfile])
        args.append(context)
        self._run(args)
        return image

    def create_network(self, name: str) -> str:
        self._run(["network", "create", name])
        return name

    def create_volume(self, name: str) -> str:
        self._run(["volume", "create", name])
        return name

    def create_container(self, spec: DockerContainerSpec) -> str:
        args = ["create", "--name", spec.name]
        if spec.network:
            args.extend(["--network", spec.network])
        if spec.healthcheck:
            args.extend(["--health-cmd", spec.healthcheck, "--health-interval", "5s", "--health-timeout", "3s", "--health-retries", "12"])
        for key, value in (spec.env or {}).items():
            args.extend(["--env", f"{key}={value}"])
        for container_port, host_port in (spec.ports or {}).items():
            args.extend(["--publish", f"{host_port}:{container_port}"])
        for volume in spec.volumes or []:
            args.extend(["--volume", volume])
        args.append(spec.image)
        args.extend(spec.command or [])
        return self._run(args) or spec.name

    def start_container(self, container_id: str) -> bool:
        self._run(["start", container_id])
        return True

    def wait_for_health(self, container_id: str, timeout_seconds: int = 60) -> bool:
        if not container_id:
            raise ToolError("Container id is required for health checks.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = self._run(["inspect", container_id])
            state = json.loads(raw)[0].get("State", {})
            health = state.get("Health", {}).get("Status")
            if health == "healthy" or (health is None and state.get("Running")):
                return True
            if state.get("Status") in {"exited", "dead"}:
                return False
            time.sleep(1)
        return False

    def exec_command(self, container_id: str, command: list[str]) -> str:
        if not container_id:
            raise ToolError("Container id is required for exec.")
        return self._run(["exec", container_id, *command])

    def read_logs(self, container_id: str) -> str:
        if not container_id:
            raise ToolError("Container id is required for logs.")
        return self._run(["logs", container_id])

    def stop_container(self, container_id: str) -> bool:
        if not container_id:
            return False
        self._run(["stop", container_id])
        return True

    def remove_container(self, container_id: str) -> bool:
        if not container_id:
            return False
        self._run(["rm", "--force", container_id])
        return True

    def remove_network(self, name: str) -> bool:
        if not name:
            return False
        self._run(["network", "rm", name])
        return True

    def remove_volume(self, name: str) -> bool:
        if not name:
            return False
        self._run(["volume", "rm", "--force", name])
        return True

    def remove_image(self, image: str) -> bool:
        if not image:
            return False
        self._run(["image", "rm", "--force", image])
        return True


def build_docker_tools(docker: DockerMCP) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MCPTool("build_image", "Build a repair image for a copy of the project.", docker.build_image))
    registry.register(MCPTool("create_network", "Create a temporary repair network.", docker.create_network))
    registry.register(MCPTool("create_volume", "Create a temporary repair volume.", docker.create_volume))
    registry.register(MCPTool("create_container", "Create a container in the repair stack.", docker.create_container))
    registry.register(MCPTool("start_container", "Start a repair container.", docker.start_container))
    registry.register(MCPTool("wait_for_health", "Wait for a repair service to become healthy.", docker.wait_for_health))
    registry.register(MCPTool("exec_command", "Execute a command inside a repair container.", docker.exec_command))
    registry.register(MCPTool("read_logs", "Read logs from a repair container.", docker.read_logs))
    registry.register(MCPTool("stop_container", "Stop a repair container.", docker.stop_container))
    registry.register(MCPTool("remove_container", "Remove a repair container.", docker.remove_container))
    registry.register(MCPTool("remove_network", "Remove a repair network.", docker.remove_network))
    registry.register(MCPTool("remove_volume", "Remove a repair volume.", docker.remove_volume))
    registry.register(MCPTool("remove_image", "Remove a temporary repair image.", docker.remove_image))
    return registry
