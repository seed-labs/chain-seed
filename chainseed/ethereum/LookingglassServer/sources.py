"""Lookingglass data readers. No Docker commands, subprocesses, or experiment writes."""
import csv
import hashlib
import io
import json
import math
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import yaml

PREFIX = "org.seedsecuritylabs.seedemu.meta."


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def recent(value, now, max_age=180):
    return value is not None and 0 <= now - value < max_age


def network_summary(nodes, now=None, max_age=30):
    """Aggregate fresh node samples, not a synchronized global chain state."""
    now = time.time() if now is None else now
    beacons = [n for n in nodes if n["role"] == "beacon"]
    geths = [n for n in nodes if n["role"] == "geth"]

    def fresh(sample):
        at = number(sample.get("at"))
        return at is not None and 0 <= now - at <= max_age

    def stats(values):
        values = sorted(values)
        return {"count": len(values), "mean": sum(values) / len(values) if values else None,
                "p95": values[math.ceil(len(values) * .95) - 1] if values else None,
                "max": values[-1] if values else None}

    queues = {}
    for node in beacons:
        # A previous successful sample may still exist after a failed query.
        if node.get("metrics_error"):
            continue
        for metric in node.get("metrics", []):
            value = number(metric.get("queue_mean"))
            if fresh(metric) and value is not None and value >= 0:
                queues.setdefault(metric["type"], []).append(value)
    pools = [n["txpool"] for n in geths if n.get("txpool") and not n.get("metrics_error")
             and fresh(n["txpool"]) and all(number(n["txpool"].get(k)) is not None
                                           and number(n["txpool"][k]) >= 0 for k in ("pending", "queued"))]
    pending = [number(p["pending"]) for p in pools]
    queued = [number(p["queued"]) for p in pools]
    total = [p + q for p, q in zip(pending, queued)]
    return {"at": now, "max_age_seconds": max_age, "beacons_total": len(beacons),
            "queues": {kind: stats(values) for kind, values in sorted(queues.items())},
            "geths_total": len(geths), "geths_sampled": len(pools),
            "txpool": {"pending_copies": sum(pending) if pools else None,
                       "queued_copies": sum(queued) if pools else None,
                       "total_copies": sum(total) if pools else None,
                       "per_node": stats(total), "unique_transactions": None}}


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def csv_tail(path, budget=768_000):
    """Bounded recent window, never label a partial tail as whole-run data.

    Large event/transaction CSVs have single-line records. CSV strict parsing
    rejects incomplete trailing records; snapshot CSVs (including multiline
    commands) are read whole when smaller than their explicit budget.
    """
    try:
        with path.open("rb") as stream:
            header = stream.readline().decode("utf-8")
            start = stream.tell()
            size = path.stat().st_size
            if size - start > budget:
                stream.seek(size - budget)
                stream.readline()
            body = stream.read(budget + 65536).decode("utf-8", errors="replace")
        if not body.endswith("\n"):
            body = body.rsplit("\n", 1)[0] + "\n" if "\n" in body else ""
        reader = csv.DictReader(io.StringIO(header + body), strict=True)
        rows = []
        try:
            for row in reader:
                if None not in row and all(v is not None for v in row.values()):
                    rows.append(row)
        except csv.Error:
            pass
        return rows
    except OSError:
        return []


def role_of(name):
    for word in ("beacon", "geth", "validator"):
        if re.search(rf"POS-{word}-\d+", name, re.I):
            return word
    return "other"


def short_name(name):
    match = re.search(r"POS-(Beacon|Geth|Validator)-(\d+)", name)
    return {"Beacon": "BN", "Geth": "EL", "Validator": "VC"}[match[1]] + "-" + match[2] if match else name


class RunSource:
    """Read the independent Ethereum collectors' output without changing it."""
    def __init__(self, run=None, compose=None, tx_dir=None, receipts=None, inventory=None):
        self.inventory_mode = inventory is not None
        self.inventory = read_json(Path(inventory)) if inventory is not None else {}
        self.run = Path(run).resolve() if run is not None else Path(inventory).resolve().parent
        self.compose = Path(compose).resolve() if compose else self.run / "observed-compose.yml"
        if not self.inventory_mode and not self.compose.is_file():
            raise ValueError("Run measure.py first, or pass --compose PATH")
        self.tx_dir = Path(tx_dir).resolve() if tx_dir else self.run / "tx-load"
        self.receipts = Path(receipts).resolve() if receipts else self.run / "tx_receipts.csv"
        self.config = read_json(self.run / "deployment.json")
        if not self.config:
            self.config = read_json(self.compose.with_name("deployment.json"))
        doc = yaml.safe_load(self.compose.read_text()) if not self.inventory_mode else {}
        self.nodes = {}
        for service, cfg in doc.get("services", {}).items():
            name = cfg.get("container_name", service)
            labels = cfg.get("labels", {})
            if isinstance(labels, list):
                labels = dict(item.split("=", 1) for item in labels if "=" in item)
            display = labels.get(PREFIX + "displayname", name)
            role = role_of(display)
            if role == "other":
                continue
            ip = str(labels.get(PREFIX + "net.0.address", "")).split("/")[0]
            if not ip:
                ip = next((v.get("ipv4_address", "") for v in cfg.get("networks", {}).values()
                           if isinstance(v, dict)), "")
            self.nodes[name] = {
                "id": name, "label": short_name(display), "service": service,
                "role": role, "asn": str(labels.get(PREFIX + "asn", "?")),
                "ip": ip, "memory_gib": None, "cpu": None,
                "at": None, "metrics": [], "series": [], "head": None,
                "keys": self.config.get("keys_per_client") if role == "validator" else None,
                "cap": self.config.get("worker_cap") if role == "beacon" else None,
            }
        self.configured_edges = self.inventory.get("edges", [])
        if self.inventory_mode:
            self.nodes = {
                item["id"]: {"memory_gib": None, "cpu": None, "at": None,
                             "metrics": [], "series": [], "head": None,
                             "keys": None, "cap": None, **item}
                for item in self.inventory.get("nodes", [])
            }
        if not self.nodes and not self.inventory_mode:
            raise ValueError("Compose contains no Ethereum PoS Beacon, Geth or Validator nodes")
        self.history = {name: deque(maxlen=60) for name in self.nodes}
        self.last_memory_sample = {}
        self.tail_cache = {}
        self.event_rows = None
        self.event_cache = []
        self.observation_aliases = {}
        self._compose_signature = None

    def refresh_aliases(self):
        """Associate optional legacy collector names by explicit AS/host labels."""
        if not self.inventory_mode:
            return
        try:
            stat = self.compose.stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if signature == self._compose_signature:
                return
            doc = yaml.safe_load(self.compose.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return
        aliases = {}
        for service, spec in doc.get("services", {}).items():
            labels = spec.get("labels", {})
            if isinstance(labels, list):
                labels = dict(item.split("=", 1) for item in labels if "=" in item)
            matches = [node for node in self.nodes.values()
                       if node.get("host") == labels.get(PREFIX + "nodename")
                       and node["asn"] == str(labels.get(PREFIX + "asn"))]
            # A shared host may have multiple client roles; do not guess an ID.
            if len(matches) == 1:
                aliases[spec.get("container_name", service)] = matches[0]["id"]
        self.observation_aliases = aliases
        self._compose_signature = signature
        self.event_rows = None

    def observation_node(self, name):
        return self.nodes.get(self.observation_aliases.get(name, name))

    def tail(self, path, budget=768_000):
        path = Path(path)
        if not path.is_absolute():
            path = self.run / path
        try:
            stat = path.stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except OSError:
            return []
        previous = self.tail_cache.get(path)
        if previous and previous[0] == signature:
            return previous[1]
        rows = csv_tail(path, budget)
        self.tail_cache[path] = (signature, rows)
        return rows

    def block_events(self):
        rows = self.tail("consensus/block_first_seen.csv", 1_000_000)
        if rows is not self.event_rows:
            self.event_cache = [
                {"node": self.observation_node(row["beacon_name"])["id"], "hash": row["head_root"],
                 "slot": row["head_slot"], "at": timestamp(row["timestamp"]),
                 "stage": "head (polled)", "evidence": "collector round timestamp", "peer": None}
                for row in rows
                if self.observation_node(row.get("beacon_name")) is not None and row.get("head_root")
                and timestamp(row.get("timestamp")) is not None
            ][-4000:]
            self.event_rows = rows
        return self.event_cache

    def snapshot(self, include_events=True):
        now = time.time()
        self.refresh_aliases()
        config = read_json(self.run / "deployment.json") or self.config
        for node in ([] if self.inventory_mode else self.nodes.values()):
            if node["role"] == "validator":
                node["keys"] = config.get("keys_per_client")
            elif node["role"] == "beacon":
                node["cap"] = config.get("worker_cap")
        rows = self.tail("memory_latest_raw.csv", 16_000_000)
        relations = {(e["source"], e["target"]): dict(e) for e in self.configured_edges}
        by_ip = {node["ip"]: name for name, node in self.nodes.items() if node["ip"]}
        for row in rows:
            node = self.observation_node(row.get("container_name"))
            if not node:
                continue
            mem = number(row.get("mem_usage_bytes"))
            node.update(memory_gib=mem / 2**30 if mem is not None else None,
                        cpu=number(row.get("cpu_percent")), at=timestamp(row.get("timestamp")))
            sample = (row.get("sample"), row.get("timestamp"))
            if sample != self.last_memory_sample.get(node["id"]):
                self.history[node["id"]].append({"at": node["at"], "memory": node["memory_gib"], "cpu": node["cpu"]})
                self.last_memory_sample[node["id"]] = sample
            command = row.get("main_cmd", "")
            flag = {"validator": "beacon-nodes", "beacon": "execution-endpoint"}.get(node["role"])
            if flag:
                match = re.search(r"--" + flag + r"[ =]+http://([\d.]+):", command)
                if match and match[1] in by_ip:
                    target = by_ip[match[1]]
                    relations[(node["id"], target)] = {"source": node["id"], "target": target,
                                                       "kind": "service", "at": node["at"]}
        for row in self.tail("consensus/beacon_head_samples.csv"):
            node = self.observation_node(row.get("beacon_name"))
            if node is not None and not row.get("error"):
                node.update(head=number(row.get("head_slot")), head_at=timestamp(row.get("timestamp")))
        for node in self.nodes.values():
            node["series"] = list(self.history[node["id"]])
        transactions = {}
        for row in self.tail(self.tx_dir / "tx_sender.csv", 256_000):
            if row.get("tx_hash") and row.get("status") == "sent":
                ip_match = re.search(r"http://([\d.]+):", row.get("rpc_url", ""))
                transactions[row["tx_hash"]] = {
                    "hash": row["tx_hash"], "kind": row.get("tx_type"),
                    "node": by_ip.get(ip_match[1]) if ip_match else None,
                    "accepted_at": timestamp(row.get("timestamp")), "receipt_at": None,
                    "block": None, "status": "RPC accepted; receipt outside recent window or pending",
                }
        for row in self.tail(self.receipts, 256_000):
            if not row.get("tx_hash"):
                continue
            tx = transactions.setdefault(row["tx_hash"], {
                "hash": row["tx_hash"], "kind": row.get("tx_type"), "node": None,
                "accepted_at": timestamp(row.get("accepted_timestamp")),
            })
            status = {"1": "success", "0": "failed"}.get(row.get("status"), "unknown")
            tx.update(receipt_at=timestamp(row.get("commit_observed_timestamp")),
                      block=row.get("block_number"), status="Included / execution " + status)
        sample_time = max((n["at"] or 0 for n in self.nodes.values()), default=0)
        collector = read_json(self.run / "run_info.json")
        fresh = recent(sample_time, now)
        # Probes belong to an active measurement. A stopped/crashed collector
        # pauses them, even though archived data remains available in the UI.
        probing_allowed = (
            fresh and collector.get("status") == "running"
            and recent(timestamp(collector.get("updated_at")), now)
            and all(recent(n["at"], now) for n in self.nodes.values())
        )
        return {
            "mode": "live" if self.inventory_mode else "recorded",
            "run": self.inventory.get("title", self.inventory.get("chain", self.run.name)),
            "chains": self.inventory.get("chains", []), "generated_at": now,
            "sample_at": sample_time, "fresh": fresh,
            "probing_allowed": self.inventory_mode or probing_allowed,
            "collector_status": collector.get("status", "not started"),
            "nodes": [dict(node) for node in self.nodes.values()], "edges": list(relations.values()),
            "events": self.block_events() if include_events else [],
            "transactions": sorted(transactions.values(), key=lambda t: t.get("accepted_at") or 0)[-500:],
            "processor": {"caught_up": False, "error": None, "source": "disabled; use --probe-peers"},
            "capabilities": {
                "peer_graph": "Disabled: enable optional read-only probes",
                "peer_origin": "Unavailable without client instrumentation",
                "history": "Recent file tail + resources since attachment",
            },
            "explorer_url": "",
        }


def demo_snapshot():
    """Deterministic synthetic fixture; never mixed into experimental records."""
    now = time.time()
    nodes, edges, events = [], [], []
    for i in range(36):
        asn = str(150 + i // 6)
        for role, prefix in (("beacon", "BN"), ("geth", "EL"), ("validator", "VC")):
            name = f"{prefix}-{i:03d}"
            mem = {"beacon": .43, "geth": .61, "validator": .047}[role] + (i % 7) * .013
            nodes.append({"id": name, "label": name, "role": role, "asn": asn,
                          "ip": f"10.{asn}.0.{70+i%6*3+['beacon','geth','validator'].index(role)}",
                          "memory_gib": mem, "cpu": 3 + i % 18, "at": now,
                          "head": 18240 if role == "beacon" else None,
                          "keys": 3 if role == "validator" else None, "cap": "2" if role == "beacon" else None,
                          "metrics": [{"type": "api_request_p0", "queue_mean": .2 + (i % 9) * .4, "workers": 2, "peers": 4, "at": now}] if role == "beacon" else [],
                          "series": [{"at": now - (39-j)*15, "memory": mem*(.9+.1*j/40), "cpu": 3+(i+j)%18} for j in range(40)]})
        edges.extend([{"source": f"VC-{i:03d}", "target": f"BN-{i:03d}", "kind": "service", "at": now},
                      {"source": f"BN-{i:03d}", "target": f"EL-{i:03d}", "kind": "service", "at": now}])
        for prefix in ("BN", "EL"):
            for offset in (1, 6):
                edges.append({"source": f"{prefix}-{i:03d}", "target": f"{prefix}-{(i+offset)%36:03d}", "kind": "peer", "at": now, "evidence": "synthetic"})
        for slot in range(18235, 18241):
            events.append({"node": f"BN-{i:03d}", "hash": "0x"+hashlib.sha256(str(slot).encode()).hexdigest(),
                           "slot": str(slot), "at": now-((18240-slot)*12+4)+i*.075,
                           "stage": "head", "peer": None, "evidence": "synthetic observation"})
    return {"mode": "demo", "run": "Synthetic interaction fixture / not experiment evidence", "generated_at": now,
            "sample_at": now, "fresh": True, "nodes": nodes, "edges": edges, "events": events,
            "transactions": [{"hash": "0x"+"ab"*32, "kind": "token_transfer", "node": "EL-000", "accepted_at": now-12, "receipt_at": now-1, "block": "18122", "status": "Included / execution success"}],
            "processor": {"caught_up": True, "error": None, "source": "synthetic"}, "capabilities": {"peer_graph": "Synthetic fixture", "peer_origin": "Not modeled", "history": "Synthetic 10-minute resource window"}, "explorer_url": ""}
