#!/usr/bin/env python3
"""Step 0: ensure docling-server container is running."""

from __future__ import annotations

import argparse
import subprocess

DEFAULT_CONTAINER_NAME = "docling-server"
DEFAULT_IMAGE = "quay.io/docling-project/docling-serve:latest"
DEFAULT_HOST_PORT = "5001"
DEFAULT_CONTAINER_PORT = "5001"


class InitError(RuntimeError):
    """Raised when docling-server initialization fails."""


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise InitError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _container_exists(name: str) -> bool:
    out = _run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
    return out.strip() == name


def _container_running(name: str) -> bool:
    out = _run(["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
    return out.strip() == name


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 0 docling-server initializer")
    parser.add_argument("--container-name", default=DEFAULT_CONTAINER_NAME)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--host-port", default=DEFAULT_HOST_PORT)
    parser.add_argument("--container-port", default=DEFAULT_CONTAINER_PORT)
    args = parser.parse_args()

    if _container_running(args.container_name):
        print(f"already-running:{args.container_name}")
        return 0

    if _container_exists(args.container_name):
        _run(["docker", "start", args.container_name])
        print(f"started-existing:{args.container_name}")
        return 0

    _run(["docker", "pull", args.image])
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            args.container_name,
            "-p",
            f"{args.host_port}:{args.container_port}",
            args.image,
        ]
    )
    print(f"started-new:{args.container_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

