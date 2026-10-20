#!/usr/bin/env python3
# encoding: utf-8

"""Helpers for driving the private Solana cluster from example scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

BOOTSTRAP_PREFIX = "as150h-Solana-Bootstrap-150-"
RPC_URL = "http://127.0.0.1:8899"


def run_command(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture stdout/stderr."""
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def exit_with_process_error(context: str, proc: subprocess.CompletedProcess[str]) -> None:
    """Print a failed subprocess result and exit."""
    print(f"[fail] {context}", file=sys.stderr)
    if proc.stdout:
        print(proc.stdout, file=sys.stderr, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    raise SystemExit(proc.returncode or 1)


def find_bootstrap_container() -> str:
    """Return the running bootstrap container name."""
    proc = run_command(["docker", "ps", "--format", "{{.Names}}"])
    if proc.returncode != 0:
        exit_with_process_error("docker ps failed", proc)

    for name in proc.stdout.splitlines():
        if name.startswith(BOOTSTRAP_PREFIX):
            return name

    print(
        f"[fail] no running bootstrap container found ({BOOTSTRAP_PREFIX}...).",
        file=sys.stderr,
    )
    print("Run ./prepare_solana.sh first.", file=sys.stderr)
    raise SystemExit(1)


def exec_shell(container: str, script: str) -> str:
    """Run a shell script inside the bootstrap container."""
    proc = run_command(["docker", "exec", "-i", container, "sh", "-s"], input_text=script)
    if proc.returncode != 0:
        exit_with_process_error("docker exec failed", proc)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    return proc.stdout


def docker_cp(src: Path, container: str, dst: str) -> None:
    """Copy a local file into a container."""
    proc = run_command(["docker", "cp", str(src), f"{container}:{dst}"])
    if proc.returncode != 0:
        exit_with_process_error("docker cp failed", proc)
