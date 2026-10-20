#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from eth_account import Account


Account.enable_unaudited_hdwallet_features()

CHAIN_ID = 202705
MNEMONIC = "gentle always fun glass foster produce north tail security list example gain"
GAS_LOW = 95_000_000_000
GAS_MID = 100_000_000_000
GAS_HIGH = 105_000_000_000
GAS_LIMIT = 21_000


@dataclass(frozen=True)
class TxFamily:
    account_index: int
    sender: str
    source: str
    sink: str
    blockers: list[str]
    low_hash: str
    mid_hash: str
    high_hash: str


def run(cmd: list[str], timeout: int = 20, check: bool = False) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    result = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if check and proc.returncode:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def run_stdin(cmd: list[str], stdin: str, timeout: int = 20, check: bool = False) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(cmd, input=stdin, text=True, capture_output=True, timeout=timeout)
    result = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if check and proc.returncode:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def dexec(container: str, *args: str, timeout: int = 20, check: bool = False) -> dict[str, Any]:
    return run(["docker", "exec", container, *args], timeout=timeout, check=check)


def role_number(role: str) -> int:
    return int(role[1:])


def discover_containers(limit: int | None = None) -> tuple[str, dict[str, str], dict[str, str]]:
    result = run(["docker", "ps", "--format", "{{.Names}}"], check=True)
    names = result["stdout"].splitlines()
    miner_matches = [name for name in names if "-TopoShot-Scale-Miner-" in name]
    if len(miner_matches) != 1:
        raise RuntimeError(f"expected exactly one TopoShot scale miner, got {miner_matches}")
    nodes: dict[str, str] = {}
    for name in names:
        match = re.search(r"-TopoShot-Scale-N(\d{3})-", name)
        if match:
            role = f"N{int(match.group(1)):03d}"
            nodes[role] = name
    ordered_roles = sorted(nodes, key=role_number)
    if limit is not None:
        ordered_roles = ordered_roles[:limit]
    selected = {role: nodes[role] for role in ordered_roles}
    if len(selected) < 4:
        raise RuntimeError(f"expected at least 4 TopoShot scale nodes, got {selected}")
    ips = {"M": ip_from_container_name(miner_matches[0])}
    for role, container in selected.items():
        ips[role] = ip_from_container_name(container)
    return miner_matches[0], selected, ips


def ip_from_container_name(name: str) -> str:
    match = re.search(r"(10\.\d+\.\d+\.\d+)$", name)
    if not match:
        raise RuntimeError(f"could not parse SEED host IP from container name {name}")
    return match.group(1)


def rpc(container: str, method: str, params: list[Any] | None = None, timeout: int = 10) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": int(time.time() * 1000000) % 10000000, "method": method, "params": params or []})
    result = dexec(
        container,
        "curl",
        "--max-time",
        str(timeout),
        "-s",
        "-H",
        "Content-Type: application/json",
        "--data",
        payload,
        "http://127.0.0.1:8545",
        timeout=timeout + 5,
        check=True,
    )
    try:
        data = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json RPC response for {method}: {result}") from exc
    if "error" in data:
        raise RuntimeError(f"RPC {method} failed: {data['error']}")
    return data.get("result")


def wait_for_rpc(miner: str, containers: dict[str, str], timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    observations: list[dict[str, Any]] = []
    all_containers = {"M": miner, **containers}
    while time.time() < deadline:
        ready: dict[str, Any] = {}
        for role, container in all_containers.items():
            try:
                ready[role] = {
                    "net_version": rpc(container, "net_version", timeout=5),
                    "client": rpc(container, "web3_clientVersion", timeout=5),
                }
            except Exception as exc:
                ready[role] = {"error": str(exc)}
        observations.append(ready)
        if all("error" not in row for row in ready.values()):
            return {"ready": True, "observations": observations, "clients": ready}
        time.sleep(3)
    return {"ready": False, "observations": observations}


def node_enodes(miner: str, containers: dict[str, str], ips: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    all_containers = {"M": miner, **containers}
    for role, container in all_containers.items():
        info = rpc(container, "admin_nodeInfo")
        enode = info["enode"]
        node_id = enode.split("://", 1)[1].split("@", 1)[0]
        out[role] = f"enode://{node_id}@{ips[role]}:30303"
    return out


def peers(container: str) -> list[dict[str, Any]]:
    return rpc(container, "admin_peers")


def peer_roles(container: str, ips: dict[str, str]) -> set[str]:
    rows = peers(container)
    out: set[str] = set()
    for row in rows:
        remote = row.get("network", {}).get("remoteAddress", "")
        for role, ip in ips.items():
            if ip in remote:
                out.add(role)
    return out


def remove_all_peers(containers: dict[str, str], enodes: dict[str, str], roles: list[str]) -> None:
    for _ in range(8):
        active = 0
        for role in roles:
            container = containers[role]
            rows = peers(container)
            active += len(rows)
            for row in rows:
                enode = row.get("enode")
                if enode:
                    try:
                        rpc(container, "admin_removePeer", [enode], timeout=5)
                    except Exception:
                        pass
        if active == 0:
            break
        time.sleep(1)


def block_number(container: str) -> int:
    return int(rpc(container, "eth_blockNumber"), 16)


def sync_with_miner(miner: str, containers: dict[str, str], enodes: dict[str, str], ips: dict[str, str], roles: list[str], timeout: int) -> dict[str, Any]:
    remove_all_peers(containers, enodes, roles)
    for role in roles:
        rpc(containers[role], "admin_addPeer", [enodes["M"]])

    deadline = time.time() + timeout
    observations: list[dict[str, Any]] = []
    ready = False
    while time.time() < deadline:
        heights = {"M": block_number(miner)}
        heights.update({role: block_number(containers[role]) for role in roles})
        syncing = {role: rpc(containers[role], "eth_syncing") for role in roles}
        observed_peers = {role: sorted(peer_roles(containers[role], ips)) for role in roles}
        row = {"heights": heights, "syncing": syncing, "observed_peers": observed_peers}
        observations.append(row)
        if (
            heights["M"] > 0
            and all(heights[role] >= max(1, heights["M"] - 1) for role in roles)
            and all(syncing[role] is False for role in roles)
            and all("M" in observed_peers[role] for role in roles)
        ):
            ready = True
            break
        time.sleep(5)

    remove_all_peers(containers, enodes, roles)
    return {
        "ready": ready,
        "observations": observations,
        "final_active_peers": {role: sorted(peer_roles(containers[role], ips) & set(roles)) for role in roles},
    }


def normalize(edge: tuple[str, str]) -> tuple[str, str]:
    a, b = edge
    return (a, b) if role_number(a) <= role_number(b) else (b, a)


def complete_candidates(roles: list[str]) -> list[tuple[str, str]]:
    return [(roles[i], roles[j]) for i in range(len(roles)) for j in range(i + 1, len(roles))]


def topology_edges(name: str, roles: list[str], seed: int) -> set[tuple[str, str]]:
    n = len(roles)
    rng = random.Random(f"{seed}:{name}:{n}")
    edges: set[tuple[str, str]] = set()

    if name == "empty":
        return edges
    if name == "path":
        return {normalize((roles[i], roles[i + 1])) for i in range(n - 1)}
    if name == "ring":
        return {normalize((roles[i], roles[(i + 1) % n])) for i in range(n)}
    if name == "star":
        return {normalize((roles[0], roles[i])) for i in range(1, n)}
    if name == "complete":
        return set(complete_candidates(roles))
    if name == "balanced_bipartite":
        left = roles[: n // 2]
        right = roles[n // 2 :]
        return {normalize((a, b)) for a in left for b in right}
    if name == "lollipop":
        clique_size = max(3, n // 2)
        for i in range(clique_size):
            for j in range(i + 1, clique_size):
                edges.add(normalize((roles[i], roles[j])))
        for i in range(clique_size - 1, n - 1):
            edges.add(normalize((roles[i], roles[i + 1])))
        return edges
    if name == "random_deg3":
        target_degree = min(3, n - 1)
        possible = complete_candidates(roles)
        rng.shuffle(possible)
        degree = {role: 0 for role in roles}
        for a, b in possible:
            if degree[a] >= target_degree and degree[b] >= target_degree:
                continue
            if rng.random() < 0.55 or degree[a] == 0 or degree[b] == 0:
                edges.add(normalize((a, b)))
                degree[a] += 1
                degree[b] += 1
            if sum(degree.values()) >= n * target_degree:
                break
        return edges
    if name == "two_communities":
        split = n // 2
        groups = [roles[:split], roles[split:]]
        for group in groups:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    if (j - i) <= 2:
                        edges.add(normalize((group[i], group[j])))
        if groups[0] and groups[1]:
            edges.add(normalize((groups[0][0], groups[1][0])))
            edges.add(normalize((groups[0][-1], groups[1][-1])))
        return edges
    raise ValueError(f"unknown topology {name}")


def connect_edges(containers: dict[str, str], enodes: dict[str, str], ips: dict[str, str], roles: list[str], edges: set[tuple[str, str]], timeout: int) -> dict[str, list[str]]:
    for a, b in sorted(edges, key=lambda e: (role_number(e[0]), role_number(e[1]))):
        rpc(containers[a], "admin_addPeer", [enodes[b]], timeout=5)
        rpc(containers[b], "admin_addPeer", [enodes[a]], timeout=5)
    deadline = time.time() + timeout
    wanted = {role: set() for role in roles}
    for a, b in edges:
        wanted[a].add(b)
        wanted[b].add(a)
    while time.time() < deadline:
        observed = {role: peer_roles(containers[role], ips) & set(roles) for role in roles}
        if all(wanted[role] <= observed[role] for role in roles):
            return {role: sorted(observed[role], key=role_number) for role in roles}
        time.sleep(0.5)
    return {role: sorted(peer_roles(containers[role], ips) & set(roles), key=role_number) for role in roles}


@lru_cache(maxsize=None)
def account(index: int):
    return Account.from_mnemonic(MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")


def signed_tx(sender_index: int, gas_price: int, recipient: str):
    acct = account(sender_index)
    tx = {
        "chainId": CHAIN_ID,
        "nonce": 0,
        "gasPrice": gas_price,
        "gas": GAS_LIMIT,
        "to": recipient,
        "value": 0,
    }
    signed = Account.sign_transaction(tx, acct.key)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return acct.address, raw.hex(), signed.hash.hex()


def send_raw_chunk(container: str, raws: list[str], timeout: int) -> list[str]:
    if not raws:
        return []
    payload = json.dumps([
        {"jsonrpc": "2.0", "id": i, "method": "eth_sendRawTransaction", "params": [raw]}
        for i, raw in enumerate(raws)
    ])
    result = run_stdin(
        ["docker", "exec", "-i", container,
        "curl",
        "--max-time",
        str(timeout),
        "-s",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
        "http://127.0.0.1:8545",
        ],
        payload,
        timeout=timeout + 10,
        check=True,
    )
    data = json.loads(result["stdout"])
    by_id = {row["id"]: row for row in data}
    hashes: list[str] = []
    for i in range(len(raws)):
        row = by_id[i]
        if "error" in row:
            raise RuntimeError(f"eth_sendRawTransaction batch failed at {i}: {row['error']}")
        hashes.append(row["result"])
    return hashes


def send_raw_batch(container: str, raws: list[str], timeout: int = 90) -> list[str]:
    if not raws:
        return []
    chunk_size = 500
    hashes: list[str] = []
    for offset in range(0, len(raws), chunk_size):
        chunk = raws[offset : offset + chunk_size]
        chunk_timeout = max(timeout, min(600, 30 + len(chunk) // 4))
        hashes.extend(send_raw_chunk(container, chunk, chunk_timeout))
    return hashes


def txpool_hashes(container: str) -> set[str]:
    content = rpc(container, "txpool_content", timeout=30)
    hashes: set[str] = set()
    for section in ("pending", "queued"):
        accounts = content.get(section, {})
        for nonces in accounts.values():
            for tx in nonces.values():
                if isinstance(tx, dict) and tx.get("hash"):
                    hashes.add(tx["hash"].lower())
    return hashes


def prepare_probe(roles: list[str], account_start: int) -> tuple[list[TxFamily], dict[str, list[str]]]:
    recipient = account(0).address
    sends: dict[str, list[str]] = {role: [] for role in roles}
    families: list[TxFamily] = []
    next_account = account_start
    for source, sink in complete_candidates(roles):
        blockers = [role for role in roles if role not in (source, sink)]
        sender, raw_low, low_hash = signed_tx(next_account, GAS_LOW, recipient)
        _, raw_mid, mid_hash = signed_tx(next_account, GAS_MID, recipient)
        _, raw_high, high_hash = signed_tx(next_account, GAS_HIGH, recipient)
        sends[sink].append(raw_low)
        sends[source].append(raw_high)
        for blocker in blockers:
            sends[blocker].append(raw_mid)
        families.append(TxFamily(
            account_index=next_account,
            sender=sender,
            source=source,
            sink=sink,
            blockers=blockers,
            low_hash=low_hash,
            mid_hash=mid_hash,
            high_hash=high_hash,
        ))
        next_account += 1
    return families, sends


def score(truth: set[tuple[str, str]], predicted: set[tuple[str, str]]) -> dict[str, Any]:
    tp = len(truth & predicted)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = 1.0 if not predicted else tp / len(predicted)
    recall = 1.0 if not truth else tp / len(truth)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
    }


def run_probe_case(
    containers: dict[str, str],
    enodes: dict[str, str],
    ips: dict[str, str],
    all_roles: list[str],
    roles: list[str],
    topology: str,
    seed: int,
    account_start: int,
    propagation_wait: float,
    connect_timeout: int,
) -> dict[str, Any]:
    started = time.time()
    remove_all_peers(containers, enodes, all_roles)
    truth = topology_edges(topology, roles, seed)
    candidate_edges = set(complete_candidates(roles))
    families, sends = prepare_probe(roles, account_start)

    send_started = time.time()
    send_counts: dict[str, int] = {}
    for role in roles:
        send_raw_batch(containers[role], sends[role])
        send_counts[role] = len(sends[role])
    send_seconds = round(time.time() - send_started, 3)

    observed_peers = connect_edges(containers, enodes, ips, roles, truth, connect_timeout)
    time.sleep(propagation_wait)

    txpool_started = time.time()
    hashes_by_role = {role: txpool_hashes(containers[role]) for role in roles}
    txpool_seconds = round(time.time() - txpool_started, 3)

    predicted: set[tuple[str, str]] = set()
    observations: list[dict[str, Any]] = []
    for family in families:
        edge = normalize((family.source, family.sink))
        high_at_sink = family.high_hash.lower() in hashes_by_role[family.sink]
        if high_at_sink:
            predicted.add(edge)
        observations.append({
            **asdict(family),
            "edge": list(edge),
            "high_tx_present_at_sink": high_at_sink,
            "low_tx_present_at_sink": family.low_hash.lower() in hashes_by_role[family.sink],
            "mid_tx_present_at_blockers": {
                blocker: family.mid_hash.lower() in hashes_by_role[blocker]
                for blocker in family.blockers
            },
        })

    metrics = score(truth, predicted)
    total_seconds = round(time.time() - started, 3)
    return {
        "group_size": len(roles),
        "topology": topology,
        "candidate_edges": len(candidate_edges),
        "ground_truth_edges": [list(edge) for edge in sorted(truth, key=lambda e: (role_number(e[0]), role_number(e[1])))],
        "ground_truth_edge_count": len(truth),
        "inferred_edges": [list(edge) for edge in sorted(predicted, key=lambda e: (role_number(e[0]), role_number(e[1])))],
        "inferred_edge_count": len(predicted),
        "density": round(len(truth) / len(candidate_edges), 6) if candidate_edges else 0.0,
        "send_counts": send_counts,
        "total_transactions_submitted": sum(send_counts.values()),
        "tx_families": len(families),
        "observed_peers": observed_peers,
        "metrics": metrics,
        "timing": {
            "send_seconds": send_seconds,
            "txpool_read_seconds": txpool_seconds,
            "total_seconds": total_seconds,
            "propagation_wait_seconds": propagation_wait,
        },
        "observations": observations,
        "account_start": account_start,
        "accounts_used": len(families),
    }


def parse_int_list(text: str) -> list[int]:
    values = [int(x.strip()) for x in text.split(",") if x.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return values


def parse_str_list(text: str) -> list[str]:
    values = [x.strip() for x in text.split(",") if x.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected at least one value")
    return values


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    rows = payload["cases"]
    lines = [
        "# TopoShot live scale benchmark",
        "",
        "This table is produced by running TopoShot-style replacement-transaction probes on live Geth nodes inside a SEED BlockchainService scenario.",
        "",
        "| group | topology | candidate edges | truth edges | inferred edges | precision | recall | tx submitted | total seconds |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        metrics = row["metrics"]
        timing = row["timing"]
        lines.append(
            f"| {row['group_size']} | {row['topology']} | {row['candidate_edges']} | "
            f"{row['ground_truth_edge_count']} | {row['inferred_edge_count']} | "
            f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | "
            f"{row['total_transactions_submitted']} | {timing['total_seconds']:.3f} |"
        )
    lines.extend([
        "",
    ])
    path.write_text("\n".join(lines) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Run medium-scale TopoShot replacement-transaction probes on live SEED/Geth nodes.")
    parser.add_argument("--nodes", type=int, default=None, help="Maximum number of measured TopoShot-Scale nodes to use.")
    parser.add_argument("--group-sizes", type=parse_int_list, default=parse_int_list("4,6,8,12"))
    parser.add_argument("--topologies", type=parse_str_list, default=parse_str_list("empty,path,ring,star,balanced_bipartite,lollipop,random_deg3,complete"))
    parser.add_argument("--ready-timeout", type=int, default=180)
    parser.add_argument("--account-start", type=int, default=10)
    parser.add_argument("--propagation-wait", type=float, default=3.0)
    parser.add_argument("--connect-timeout", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20270930)
    parser.add_argument(
        "--skip-chain-sync",
        action="store_true",
        help="Skip the miner fanout synchronization check. Useful for txpool-only probes at scales where a single miner hits geth peer limits.",
    )
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent / "results" / "measurements.json"))
    parser.add_argument("--summary", default=str(Path(__file__).resolve().parent / "results" / "measurements.md"))
    parser.add_argument("--assert-success", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    miner, containers, ips = discover_containers(args.nodes)
    all_roles = sorted(containers, key=role_number)
    max_group = max(args.group_sizes)
    if max_group > len(all_roles):
        raise SystemExit(f"requested group size {max_group}, but only {len(all_roles)} measured nodes are running")

    readiness = wait_for_rpc(miner, containers, args.ready_timeout)
    if not readiness["ready"]:
        raise SystemExit(json.dumps({"readiness": readiness}, indent=2))
    enodes = node_enodes(miner, containers, ips)
    if args.skip_chain_sync:
        remove_all_peers(containers, enodes, all_roles)
        chain_sync = {
            "ready": True,
            "skipped": True,
            "reason": (
                "Skipped miner fanout synchronization because this txpool-only TopoShot probe does not require "
                "all measured nodes to stay peered with one miner. This avoids geth max-peer fanout limits at larger scales."
            ),
            "final_active_peers": {role: sorted(peer_roles(containers[role], ips) & set(all_roles)) for role in all_roles},
        }
    else:
        chain_sync = sync_with_miner(miner, containers, enodes, ips, all_roles, args.ready_timeout)
        if not chain_sync["ready"]:
            raise SystemExit(json.dumps({"readiness": readiness, "chain_sync": chain_sync}, indent=2))

    cases: list[dict[str, Any]] = []
    next_account = args.account_start
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial_output = output.with_suffix(output.suffix + ".partial")
    for group_size in args.group_sizes:
        roles = all_roles[:group_size]
        for topology in args.topologies:
            case = run_probe_case(
                containers=containers,
                enodes=enodes,
                ips=ips,
                all_roles=all_roles,
                roles=roles,
                topology=topology,
                seed=args.seed,
                account_start=next_account,
                propagation_wait=args.propagation_wait,
                connect_timeout=args.connect_timeout,
            )
            next_account += case["accounts_used"]
            cases.append(case)
            print(
                f"group={group_size} topology={topology} "
                f"precision={case['metrics']['precision']:.3f} recall={case['metrics']['recall']:.3f} "
                f"truth={case['ground_truth_edge_count']} inferred={case['inferred_edge_count']} "
                f"tx={case['total_transactions_submitted']} seconds={case['timing']['total_seconds']:.3f}"
                ,
                flush=True,
            )
            partial_output.write_text(json.dumps({
                "experiment": "medium_scale_live_toposhot_probe_benchmark_partial",
                "chain_id": CHAIN_ID,
                "parameters": {
                    "group_sizes": args.group_sizes,
                    "topologies": args.topologies,
            "seed": args.seed,
            "account_start": args.account_start,
            "accounts_used_so_far": next_account - args.account_start,
            "propagation_wait_seconds": args.propagation_wait,
            "skip_chain_sync": args.skip_chain_sync,
        },
                "cases_completed": len(cases),
                "cases": cases,
            }, indent=2, sort_keys=True))

    remove_all_peers(containers, enodes, all_roles)
    payload = {
        "reference": "TopoShot: Uncovering Ethereum's Network Topology Leveraging Replacement Transactions",
        "reference_url": "https://doi.org/10.1145/3487552.3487814",
        "pdf_url": "https://tristartom.github.io/docs/imc21-toposhot.pdf",
        "experiment": "medium_scale_live_toposhot_probe_benchmark",
        "chain_id": CHAIN_ID,
        "containers": {"miner": miner, "nodes": containers},
        "ips": ips,
        "parameters": {
            "group_sizes": args.group_sizes,
            "topologies": args.topologies,
            "seed": args.seed,
            "account_start": args.account_start,
            "accounts_used": next_account - args.account_start,
            "propagation_wait_seconds": args.propagation_wait,
            "skip_chain_sync": args.skip_chain_sync,
            "gas_price_low_txB": GAS_LOW,
            "gas_price_mid_txC": GAS_MID,
            "gas_price_high_txA": GAS_HIGH,
        },
        "readiness": readiness,
        "chain_sync": chain_sync,
        "enodes": enodes,
        "method": (
            "For each candidate pair in a measured group, the runner uses a unique account: "
            "95%-priced txB is injected at the sink, 100%-priced txC is injected at every other group node, "
            "and 105%-priced txA is injected at the source before the ground-truth overlay is connected. "
            "A source-sink edge is inferred when txA appears at the sink. The 105% price is high enough "
            "to replace txB but below Geth's replacement threshold over txC, so indirect paths through blockers "
            "are suppressed."
        ),
        "cases": cases,
    }

    output.write_text(json.dumps(payload, indent=2, sort_keys=True))
    summary = Path(args.summary)
    summary.parent.mkdir(parents=True, exist_ok=True)
    write_summary(summary, payload)
    print(f"wrote {output}")
    print(f"wrote {summary}")

    if args.assert_success:
        failures = [
            f"group={case['group_size']} topology={case['topology']} precision={case['metrics']['precision']} recall={case['metrics']['recall']}"
            for case in cases
            if case["metrics"]["precision"] != 1.0 or case["metrics"]["recall"] != 1.0
        ]
        if failures:
            raise AssertionError("; ".join(failures))
        print("PASS runtime_scale_probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
