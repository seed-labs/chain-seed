#!/usr/bin/env python3
"""Lookingglass HTTP application. GET-only UI; experiment files are read-only."""
import argparse
import copy
import gzip
import ipaddress
import json
import os
import re
import signal
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

from .sources import RunSource, demo_snapshot, network_summary, number, recent

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_static(filename):
    """Read packaged assets, including on base images with Python 3.8."""
    if hasattr(resources, "files"):
        return resources.files(__package__).joinpath("static", filename).read_bytes()
    return resources.read_binary(__package__ + ".static", filename)


def bind_address(value):
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("--host must be an IPv4 address") from exc


def fetch(url, payload=None, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with NO_PROXY.open(req, timeout=1.5) as response:
        body = response.read(2_000_000)
        return body.decode() if raw else json.loads(body)


class PeerProbe:
    """Independent bounded peer and metrics sweeps; no mutating RPC methods."""
    def __init__(self, nodes, live_heads=False):
        self.nodes = [n for n in nodes if n["role"] in ("beacon", "geth") and n["ip"]
                      and n.get("rpc_port", 8545 if n["role"] == "geth" else 8000) is not None]
        self.identities = {}
        self.samples = {}
        self.lock = threading.Lock()
        self.cursor = 0
        self.previous_metrics = {}
        self.telemetry = {}
        self.live_heads = live_heads
        self.events = deque(maxlen=4000)
        self.last_heads = {}

    @staticmethod
    def rpc(node, method):
        response = fetch(f"http://{node['ip']}:{node.get('rpc_port', 8545)}", {"jsonrpc": "2.0", "id": 1, "method": method, "params": []})
        if "error" in response:
            raise ValueError(str(response["error"]))
        return response["result"]

    @staticmethod
    def allowed(node):
        try:
            address = ipaddress.ip_address(node["ip"])
            return address.is_private and not (address.is_loopback or address.is_link_local)
        except ValueError:
            return False

    def metrics(self, node):
        port = node.get("metrics_port", 5054)
        if port is None:
            return []
        payload = fetch(f"http://{node['ip']}:{port}/metrics", raw=True)
        values = {}
        for line in payload.splitlines():
            match = re.match(r'^(beacon_processor_[\w]+|libp2p_peers)(?:\{([^}]*)\})?\s+(\S+)', line)
            if not match:
                continue
            name, labels, value = match.groups()
            typ = re.search(r'type="([^"]+)"', labels or "")
            values[(name, typ[1] if typ else "")] = number(value)
        types = sorted({typ for name, typ in values if typ and name.endswith("queue_length_count")})
        metrics = []
        for typ in types:
            count = values.get(("beacon_processor_work_event_queue_length_count", typ))
            total = values.get(("beacon_processor_work_event_queue_length_sum", typ))
            prev = self.previous_metrics.get((node["id"], typ))
            avg = None
            if count is not None and total is not None:
                if prev and count > prev[0] and total >= prev[1]:
                    avg = (total - prev[1]) / (count - prev[0])
                self.previous_metrics[(node["id"], typ)] = (count, total)
            metrics.append({"type": typ, "queue_mean": avg, "workers": values.get(("beacon_processor_workers_active_total", "")),
                            "peers": values.get(("libp2p_peers", "")), "at": time.time(), "source": "read-only metrics probe"})
        return metrics

    def poll_peer(self, node):
        if not self.allowed(node):
            return
        address = node["ip"]
        if self.live_heads and node["role"] == "beacon":
            try:
                head = fetch(f"http://{address}:{node.get('rpc_port', 8000)}/eth/v1/beacon/headers/head")["data"]
                now = time.time()
                with self.lock:
                    self.samples.setdefault(node["id"], {}).update(
                        head=int(head["header"]["message"]["slot"]), head_at=now, head_error=None)
                    if self.last_heads.get(node["id"]) != head["root"]:
                        self.events.append({"node": node["id"], "hash": head["root"],
                                            "slot": head["header"]["message"]["slot"], "at": now,
                                            "stage": "head (queried)", "evidence": "API response observation", "peer": None})
                        self.last_heads[node["id"]] = head["root"]
            except Exception as exc:
                with self.lock:
                    self.samples.setdefault(node["id"], {}).update(head_error=str(exc)[:160])
        try:
            if node["role"] == "beacon":
                base = f"http://{address}:{node.get('rpc_port', 8000)}"
                identity = fetch(base + "/eth/v1/node/identity")["data"]["peer_id"] if node["id"] not in self.identities else self.identities[node["id"]]
                peers = fetch(base + "/eth/v1/node/peers?state=connected")["data"]
                ids = [p["peer_id"] for p in peers if p.get("state") == "connected"]
                addresses = {}
                for peer in peers:
                    match = re.search(r"/ip4/([\d.]+)/", peer.get("last_seen_p2p_address", ""))
                    if peer.get("state") == "connected" and match:
                        addresses[peer["peer_id"]] = match[1]
            else:
                identity = self.rpc(node, "admin_nodeInfo")["id"] if node["id"] not in self.identities else self.identities[node["id"]]
                peers = self.rpc(node, "admin_peers")
                ids = [p["id"] for p in peers]
                addresses = {p["id"]: p.get("network", {}).get("remoteAddress", "").rsplit(":", 1)[0] for p in peers}
            with self.lock:
                self.identities[node["id"]] = identity
                self.samples.setdefault(node["id"], {}).update(ids=ids, addresses=addresses, at=time.time(), error=None)
        except Exception as exc:
            with self.lock:
                self.samples.setdefault(node["id"], {}).update(ids=[], at=time.time(), error=str(exc)[:160])

    def poll_metrics(self, node):
        if not self.allowed(node):
            return
        try:
            if node["role"] == "beacon":
                extra = {"metrics": self.metrics(node)}
            else:
                pool = self.rpc(node, "txpool_status")
                extra = {"txpool": {"pending": int(pool["pending"], 16), "queued": int(pool["queued"], 16), "at": time.time()}}
            extra.update(metrics_error=None, metrics_checked_at=time.time())
        except Exception as exc:
            # Retain the last successful value and its timestamp, but expose failure.
            extra = {"metrics_error": str(exc)[:160], "metrics_checked_at": time.time()}
        with self.lock:
            self.samples.setdefault(node["id"], {}).update(extra)

    def run(self, kind, stop, is_fresh, interval, jobs):
        poll = self.poll_peer if kind == "peers" else self.poll_metrics
        def checked(node):
            if not stop.is_set() and is_fresh():
                poll(node)
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix=kind) as pool:
            while not stop.is_set():
                if not is_fresh():
                    stop.wait(1)
                    continue
                start = time.monotonic()
                # Each sweep finishes before another starts: slow APIs cannot
                # create overlapping sweeps or an ever-growing task backlog.
                list(pool.map(checked, self.nodes))
                elapsed = time.monotonic() - start
                with self.lock:
                    self.telemetry[kind] = {"completed_at": time.time(), "sweep_seconds": round(elapsed, 3),
                                            "interval_seconds": interval, "jobs": jobs,
                                            "overrun": elapsed > interval}
                stop.wait(max(0.1, interval - elapsed))

    def merge(self, data):
        with self.lock:
            identities, samples = dict(self.identities), copy.deepcopy(self.samples)
            telemetry = copy.deepcopy(self.telemetry)
            events = list(self.events)
        by_id = {(n.get("chain"), n["role"], identities[n["id"]]): n["id"] for n in self.nodes if n["id"] in identities}
        by_address = {(n.get("chain"), n["role"], n["ip"]): n["id"] for n in self.nodes}
        edges = {}
        for node in data["nodes"]:
            sample = samples.get(node["id"])
            if not sample:
                continue
            if "ids" in sample:
                node["peer_probe"] = {"at": sample["at"], "count": len(sample["ids"]) if not sample["error"] else None, "error": sample["error"]}
            node["metrics_error"] = sample.get("metrics_error")
            if sample.get("metrics"):
                node["metrics"] = sample["metrics"]
            if sample.get("txpool"):
                node["txpool"] = sample["txpool"]
            for key in ("head", "head_at", "head_error"):
                if key in sample:
                    node[key] = sample[key]
            for peer in sample.get("ids", []):
                target = by_id.get((node.get("chain"), node["role"], peer))
                matched_by = "peer_id"
                if not target:
                    target = by_address.get((node.get("chain"), node["role"], sample.get("addresses", {}).get(peer)))
                    matched_by = "connected_peer_address"
                if target and target != node["id"]:
                    key = tuple(sorted((target, node["id"])))
                    edge = edges.setdefault(key, {"source": key[0], "target": key[1], "kind": "peer", "at": sample["at"], "reported_by": [], "matched_by": matched_by})
                    edge["at"] = max(edge["at"], sample["at"])
                    edge["reported_by"].append(node["id"])
        data["edges"].extend(edges.values())
        if self.live_heads:
            # Keep measured polling-round events separate from live API responses.
            data["events"] = sorted([*data["events"], *events], key=lambda e: e["at"] or 0)[-4000:]
            data["sample_at"] = max([data["sample_at"], *(n.get("head_at", 0) or 0 for n in data["nodes"])])
            data["fresh"] = recent(data["sample_at"], time.time())
        errors = sum(bool(s.get("error")) for s in samples.values())
        queried = sum("ids" in s for s in samples.values())
        data["probe_timing"] = telemetry
        data["capabilities"]["peer_graph"] = f"Read-only probe: {queried}/{len(self.nodes)} queried, {errors} errors. Non-simultaneous snapshots; unmapped peers omitted."


class State:
    def __init__(self, source, explorer_url="", probes=False):
        self.source = source
        self.explorer_url = explorer_url.rstrip("/")
        self.lock = threading.Lock()
        self.payload = None
        self.payload_gzip = None
        self.events = []
        self.event_payload = None
        self.event_gzip = None
        self.event_version = 0
        self.stop = threading.Event()
        self.probe = PeerProbe(list(source.nodes.values()), live_heads=source.inventory_mode) if probes and source else None
        self.source_active = False

    def probing_allowed(self):
        return not self.stop.is_set() and self.source_active

    def update(self):
        data = self.source.snapshot() if self.source else demo_snapshot()
        data["explorer_url"] = self.explorer_url
        self.source_active = data.get("probing_allowed", False)
        if self.probe:
            self.probe.merge(data)
            data["probe_active"] = self.probing_allowed()
            data["processor"] = {
                "source": "live read-only probe", "error": None,
                "caught_up": any(n.get("metrics") for n in data["nodes"]),
            }
            if not data["probe_active"]:
                data["capabilities"]["peer_graph"] += " Probes paused; retaining last observations."
        data["network_summary"] = network_summary(data["nodes"])
        raw = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
        compressed = gzip.compress(raw, compresslevel=1)
        with self.lock:
            self.payload = raw
            self.payload_gzip = compressed
            if data["events"] != self.events or self.event_payload is None:
                self.events = data["events"]
                self.event_payload = json.dumps({"events": self.events, "generated_at": time.time()}, separators=(",", ":")).encode()
                self.event_gzip = gzip.compress(self.event_payload, compresslevel=1)
                self.event_version += 1

    def loop(self):
        while not self.stop.is_set():
            try:
                self.update()
            except Exception as exc:
                self.source_active = False
                print(f"Snapshot error (previous snapshot retained): {exc}", flush=True)
            self.stop.wait(1)

def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            compressed = False
            etag = None
            if path == "/api/status":
                with state.lock:
                    ready = state.payload is not None
                body = json.dumps({"pid": os.getpid(), "snapshot_ready": ready}).encode()
                mime = "application/json"
            elif path in ("/api/snapshot", "/api/events"):
                with state.lock:
                    if path == "/api/events":
                        body, zipped = state.event_payload, state.event_gzip
                        etag = f'"events-{state.event_version}"'
                    else:
                        body, zipped = state.payload, state.payload_gzip
                if body is not None and etag and self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                if body is None:
                    self.send_error(503, "Snapshot warming up")
                    return
                mime = "application/json"
                if "gzip" in self.headers.get("Accept-Encoding", "") and zipped is not None:
                    body, compressed = zipped, True
            else:
                files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                if path not in files:
                    self.send_error(404)
                    return
                filename, mime = files[path]
                body = read_static(filename)
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="Ethereum measure.py results directory")
    parser.add_argument("--inventory", type=Path, help="Compiled Lookingglass inventory (live component mode)")
    parser.add_argument("--demo", action="store_true", help="Explicit synthetic UI fixture")
    parser.add_argument("--compose", type=Path, help="Compose file if the results have no observed-compose.yml yet")
    parser.add_argument("--tx-dir", type=Path, help="Sender directory; defaults to RUN_DIR/tx-load")
    parser.add_argument("--receipts", type=Path, help="Receipt CSV; defaults to RUN_DIR/tx_receipts.csv")
    parser.add_argument("--host", type=bind_address, default="127.0.0.1",
                        help="Listen address; use the host LAN IPv4 for direct access (no authentication)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--explorer-url", default="", help="Optional browser-visible Explorer URL")
    parser.add_argument("--probe-peers", action="store_true", help="Opt-in low-rate peer / Metrics / txpool queries; only use for the CURRENT run")
    parser.add_argument("--peer-interval", type=float, default=3, help="Target seconds between peer sweeps")
    parser.add_argument("--peer-jobs", type=int, default=8, help="Bounded concurrent peer queries")
    parser.add_argument("--metrics-interval", type=float, default=10, help="Target seconds between Metrics/txpool sweeps (2 workers)")
    args = parser.parse_args()
    if not (args.run_dir or args.inventory or args.demo):
        parser.error("specify --run-dir, --inventory or --demo")
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    if not 1 <= args.peer_jobs <= 32 or not 1 <= args.peer_interval <= 3600 or not 2 <= args.metrics_interval <= 3600:
        parser.error("peer-jobs must be 1..32, peer-interval 1..3600, metrics-interval 2..3600")
    if args.explorer_url and urlparse(args.explorer_url).scheme not in ("http", "https"):
        parser.error("Explorer URL must use http or https")
    if args.demo and (args.run_dir or args.inventory or args.compose or args.tx_dir or args.receipts or args.probe_peers):
        parser.error("demo cannot be combined with deployment files or live probes")
    try:
        source = RunSource(args.run_dir, args.compose, args.tx_dir, args.receipts, args.inventory) if not args.demo else None
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    state = State(source, args.explorer_url, args.probe_peers)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(state))
    threading.Thread(target=state.loop, daemon=True).start()
    if state.probe:
        for kind, interval, jobs in (("peers", args.peer_interval, args.peer_jobs), ("metrics", args.metrics_interval, 2)):
            threading.Thread(target=state.probe.run, args=(kind, state.stop, state.probing_allowed, interval, jobs), daemon=True).start()
    mode = "DEMO" if args.demo else "live node queries" if args.inventory and args.probe_peers else "read-only files"
    print(f"Lookingglass: http://{args.host}:{args.port} / {mode}", flush=True)
    if not ipaddress.IPv4Address(args.host).is_loopback:
        print("WARNING: no authentication; experiment data is visible to clients reaching this port. Use a trusted network.", flush=True)
    def stop(*_):
        state.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        state.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
