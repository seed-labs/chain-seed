#!/usr/bin/env python3
"""Validate the running E03 deployment through its published Lookingglass API."""

from __future__ import annotations

import json
import os
import shlex
import time
import urllib.error
import urllib.request

from chainseed.services.ethereum import LookingglassServer
from chainseed.testing import EthereumRuntimeTest


BASE_URL = os.environ.get("E03_LOOKINGGLASS_URL", "http://127.0.0.1:8765").rstrip("/")
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def record(test, name, ok, message, command="GET /api/snapshot"):
    test.results.append(dict(name=name, service="lookingglass", command=command,
                             exit=0 if ok else 1, stdout=str(message)[-2000:],
                             stderr="", status="passed" if ok else "failed"))


def save(test, filename, data):
    if test.artifact_dir:
        test.artifact_dir.mkdir(parents=True, exist_ok=True)
        (test.artifact_dir / filename).write_text(json.dumps(data, indent=2) + "\n")


def fetch(path, method="GET"):
    request = urllib.request.Request(BASE_URL + path, method=method)
    try:
        with HTTP.open(request, timeout=10) as response:
            return response.status, response.read(4_000_000).decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4_000_000).decode("utf-8", errors="replace")


def wait_json(test, name, path, check, retries=60):
    last, data = "no response", None
    deadline = time.monotonic() + retries * 5
    for attempt in range(retries):
        try:
            status, body = fetch(path)
            if status != 200:
                raise ValueError(f"HTTP {status}: {body[:200]}")
            data = json.loads(body)
            last = check(data)
            if last is None:
                record(test, name, True, f"passed after {attempt + 1} request(s)", "GET " + BASE_URL + path)
                return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            last = str(exc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if attempt + 1 < retries:
            time.sleep(min(5, remaining))
    record(test, name, False, last, "GET " + BASE_URL + path)
    save(test, "e03-last-response.json", data)
    return None


def inventory_error(data, inventory):
    if data.get("mode") != "live":
        return "Expected live inventory mode, not demo or recorded data"
    expected = {node["id"]: node for node in inventory["nodes"]}
    nodes = {node["id"]: node for node in data.get("nodes", [])}
    if len(nodes) != len(data.get("nodes", [])):
        return "Snapshot contains duplicate node IDs"
    if set(nodes) != set(expected):
        return f"Missing nodes: {set(expected) - set(nodes)}; extra nodes: {set(nodes) - set(expected)}"
    for vnode, node in nodes.items():
        for key in ("chain", "chain_id", "role", "asn", "ip", "rpc_port", "metrics_port"):
            if node.get(key) != expected[vnode].get(key):
                return f"{vnode}: {key} differs from the compiled inventory"
    edges = {(edge["source"], edge["target"]) for edge in data.get("edges", []) if edge["kind"] == "service"}
    expected_edges = {(edge["source"], edge["target"]) for edge in inventory["edges"]}
    if edges != expected_edges:
        return "Client dependencies differ from the compiled inventory"
    return None


def dependency_error(inventory):
    nodes = {node["id"]: node for node in inventory["nodes"]}
    expected = {vnode for vnode, node in nodes.items() if node["role"] in ("beacon", "validator")}
    dependencies = {}
    for edge in inventory["edges"]:
        dependencies.setdefault(edge["source"], []).append(edge["target"])
    if set(dependencies) != expected:
        return "Not every Beacon and Validator has a dependency"
    for vnode, targets in dependencies.items():
        role = "geth" if nodes[vnode]["role"] == "beacon" else "beacon"
        if len(targets) != 1 or targets[0] not in nodes:
            return f"{vnode}: expected exactly one known dependency"
        target = nodes[targets[0]]
        if target["role"] != role or target["chain"] != nodes[vnode]["chain"]:
            return f"{vnode}: dependency has the wrong role or chain"
    return None


def live_error(data, now=None):
    now = time.time() if now is None else now

    def fresh(at):
        return isinstance(at, (int, float)) and 0 <= now - at < 60

    if data.get("mode") != "live" or not data.get("probe_active"):
        return "Live client queries are not active"
    nodes = {node["id"]: node for node in data.get("nodes", [])}
    for node in nodes.values():
        if node["role"] not in ("geth", "beacon"):
            continue
        peer = node.get("peer_probe", {})
        if peer.get("error") or not fresh(peer.get("at")) or not isinstance(peer.get("count"), int) or peer["count"] < 1:
            return f"{node['id']}: no fresh connected-peer observation: {peer}"
        if node.get("metrics_error") or not fresh(node.get("metrics_checked_at")):
            return f"{node['id']}: no fresh Metrics/txpool query: {node.get('metrics_error')}"
        if node["role"] == "beacon":
            if node.get("head_error") or not fresh(node.get("head_at")) or not isinstance(node.get("head"), int) or node["head"] < 1:
                return f"{node['id']}: no fresh positive Beacon head: {node.get('head_error')}"
        else:
            pool = node.get("txpool", {})
            if not fresh(pool.get("at")) or any(not isinstance(pool.get(key), int) or pool[key] < 0
                                                for key in ("pending", "queued")):
                return f"{node['id']}: Geth txpool counts are unavailable"
    for role in ("geth", "beacon"):
        peer_edges = [edge for edge in data.get("edges", []) if edge.get("kind") == "peer"
                      and edge.get("source") in nodes and edge.get("target") in nodes
                      and nodes[edge["source"]]["role"] == nodes[edge["target"]]["role"] == role
                      and edge.get("reported_by") and fresh(edge.get("at"))]
        if not any(nodes[edge["source"]]["asn"] != nodes[edge["target"]]["asn"] for edge in peer_edges):
            return f"No observed cross-AS {role} peer connection"
    return None


def progress_error(data, before):
    if not before:
        return "No baseline Beacon heads"
    nodes = {node["id"]: node for node in data.get("nodes", [])}
    for vnode, head in before.items():
        current = nodes.get(vnode, {})
        if current.get("head_error") or not isinstance(current.get("head"), int) or current["head"] <= head:
            return f"{vnode}: observed head has not advanced beyond {head}"
    return None


def compiled_inventory(test, viewer):
    build = test.compose["services"][viewer.name]["build"]
    context = test.compose_file.parent / (build if isinstance(build, str) else build["context"])
    dockerfile = context / ("Dockerfile" if isinstance(build, str) else build.get("dockerfile", "Dockerfile"))
    target = LookingglassServer.DIR_PREFIX + "/inventory.json"
    for line in dockerfile.read_text().splitlines():
        parts = shlex.split(line)
        if len(parts) == 3 and parts[0] == "COPY" and parts[2] == target:
            return json.loads((context / parts[1]).read_text())
    raise ValueError("Compiled Lookingglass inventory was not found")


def main():
    test = EthereumRuntimeTest(__file__)
    try:
        viewers = test.require_ethereum_services("Exactly one Lookingglass Server", expected_count=1,
                                                  class_contains="Ethereum-Lookingglass")
        if not viewers:
            return 1
        viewer = viewers[0]
        spec = test.compose["services"][viewer.name]
        test.structural_check("Default host port is published automatically",
                              spec.get("ports") == ["8765:8765/tcp"], str(spec.get("ports")))
        test.structural_check("Lookingglass uses one emulated network",
                              len(spec.get("networks", {})) == 1, str(spec.get("networks")))
        inventory = compiled_inventory(test, viewer)
        save(test, "e03-inventory.json", inventory)
        counts = {role: sum(node["role"] == role for node in inventory["nodes"])
                  for role in ("geth", "beacon", "validator")}
        test.structural_check("Inventory includes every E01 client across ASes",
                              counts == dict(geth=3, beacon=3, validator=9)
                              and len({node["asn"] for node in inventory["nodes"]}) > 1,
                              str(counts))
        dependency_problem = dependency_error(inventory)
        test.structural_check("Inventory includes all Beacon and Validator dependencies",
                              dependency_problem is None, dependency_problem or "All client dependencies present")
        for path, marker in (("/", "Lookingglass"), ("/app.js", "/api/snapshot"),
                             ("/style.css", "body")):
            status, body = fetch(path)
            record(test, "Web asset " + path, status == 200 and marker in body, status, "GET " + BASE_URL + path)
        status, _ = fetch("/api/snapshot", method="POST")
        record(test, "Lookingglass HTTP API rejects writes", status in (405, 501), status, "POST /api/snapshot")
        global_data = wait_json(test, "Global snapshot matches the compiled deployment", "/api/snapshot",
                                lambda data: inventory_error(data, inventory), retries=12)
        if global_data is None:
            return 1
        observed = wait_json(test, "Every Geth and Beacon provides fresh live observations", "/api/snapshot",
                             lambda data: inventory_error(data, inventory) or live_error(data),
                             retries=90)
        if observed is None:
            return 1
        save(test, "e03-snapshot-before.json", observed)
        before = {node["id"]: node["head"] for node in observed["nodes"] if node["role"] == "beacon"}
        advanced = wait_json(test, "Every observed Beacon head continues advancing", "/api/snapshot",
                             lambda data: inventory_error(data, inventory) or live_error(data)
                             or progress_error(data, before), retries=36)
        if advanced is not None:
            save(test, "e03-snapshot-after.json", advanced)
        events = wait_json(test, "Replay contains actual Beacon head observations", "/api/events",
                           lambda data: None if any(event.get("node") in before
                               and event.get("evidence") == "API response observation"
                               for event in data.get("events", [])) else "No API-observed head event", retries=12)
        if events is not None:
            save(test, "e03-events.json", events)
    except Exception as exc:
        record(test, "E03 runtime test completed", False, repr(exc), "run E03 validation")
    finally:
        test.write_summary("e03-lookingglass-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
