#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from eth_account import Account


Account.enable_unaudited_hdwallet_features()

CHAIN_ID = 202704
MNEMONIC = "gentle always fun glass foster produce north tail security list example gain"
ROLES = {
    "M": {"container_hint": "-TopoShot-Runtime-M-", "ip": "10.240.0.71"},
    "A1": {"container_hint": "-TopoShot-Runtime-A1-", "ip": "10.241.0.71"},
    "A2": {"container_hint": "-TopoShot-Runtime-A2-", "ip": "10.242.0.71"},
    "B": {"container_hint": "-TopoShot-Runtime-B-", "ip": "10.243.0.71"},
}
ROLE_IPS = {role: spec["ip"] for role, spec in ROLES.items()}
ACTIVE_ROLES = ["A1", "A2", "B"]
CANDIDATE_EDGES = [("A1", "A2"), ("A1", "B"), ("A2", "B")]
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


def dexec(container: str, *args: str, timeout: int = 20, check: bool = False) -> dict[str, Any]:
    return run(["docker", "exec", container, *args], timeout=timeout, check=check)


def discover_containers() -> dict[str, str]:
    result = run(["docker", "ps", "--format", "{{.Names}}"], check=True)
    names = result["stdout"].splitlines()
    found: dict[str, str] = {}
    for role, spec in ROLES.items():
        matches = [name for name in names if spec["container_hint"] in name]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one container for role {role}, hint={spec['container_hint']}, got {matches}")
        found[role] = matches[0]
        ip_match = re.search(r"(10\.\d+\.\d+\.\d+)$", matches[0])
        if ip_match:
            ROLE_IPS[role] = ip_match.group(1)
    return found


def rpc(containers: dict[str, str], role: str, method: str, params: list[Any] | None = None, timeout: int = 10) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": int(time.time() * 1000000) % 10000000, "method": method, "params": params or []})
    result = dexec(
        containers[role],
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
        raise RuntimeError(f"non-json RPC response from {role} {method}: {result}") from exc
    if "error" in data:
        raise RuntimeError(f"RPC {role}.{method} failed: {data['error']}")
    return data.get("result")


def wait_for_rpc(containers: dict[str, str], timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    observations: list[dict[str, Any]] = []
    while time.time() < deadline:
        ready: dict[str, Any] = {}
        for role in ROLES:
            try:
                ready[role] = {
                    "net_version": rpc(containers, role, "net_version", timeout=5),
                    "client": rpc(containers, role, "web3_clientVersion", timeout=5),
                }
            except Exception as exc:
                ready[role] = {"error": str(exc)}
        observations.append(ready)
        if all("error" not in row for row in ready.values()):
            return {"ready": True, "observations": observations, "clients": ready}
        time.sleep(3)
    return {"ready": False, "observations": observations}


def node_enodes(containers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for role, spec in ROLES.items():
        info = rpc(containers, role, "admin_nodeInfo")
        enode = info["enode"]
        node_id = enode.split("://", 1)[1].split("@", 1)[0]
        out[role] = f"enode://{node_id}@{ROLE_IPS[role]}:30303"
    return out


def peers(containers: dict[str, str], role: str) -> list[dict[str, Any]]:
    return rpc(containers, role, "admin_peers")


def peer_roles(containers: dict[str, str], role: str) -> set[str]:
    rows = peers(containers, role)
    out: set[str] = set()
    for row in rows:
        remote = row.get("network", {}).get("remoteAddress", "")
        for candidate, ip in ROLE_IPS.items():
            if ip in remote:
                out.add(candidate)
    return out


def remove_all_peers(containers: dict[str, str], enodes: dict[str, str] | None = None) -> None:
    if enodes:
        for role in ACTIVE_ROLES:
            for candidate, enode in enodes.items():
                if candidate == role:
                    continue
                try:
                    rpc(containers, role, "admin_removePeer", [enode])
                except Exception:
                    pass
    for role in ACTIVE_ROLES:
        for row in peers(containers, role):
            enode = row.get("enode")
            if enode:
                try:
                    rpc(containers, role, "admin_removePeer", [enode])
                except Exception:
                    pass
    deadline = time.time() + 10
    while time.time() < deadline:
        if all(not peer_roles(containers, role) for role in ACTIVE_ROLES):
            time.sleep(2)
            return
        time.sleep(0.25)
    time.sleep(1)


def block_number(containers: dict[str, str], role: str) -> int:
    return int(rpc(containers, role, "eth_blockNumber"), 16)


def sync_active_nodes_with_miner(containers: dict[str, str], enodes: dict[str, str], timeout: int) -> dict[str, Any]:
    """Connect A1/A2/B to M long enough to leave the genesis-only state.

    Geth accepts local transactions while a private Clique node is still at
    genesis, but it does not gossip them reliably until the node has synced to
    a live chain head. TopoShot measures transaction propagation on running
    Ethereum nodes, so the runtime scenario first synchronizes the measured
    nodes to M, then disconnects M before constructing the controlled overlay.
    """

    remove_all_peers(containers, enodes)
    for role in ACTIVE_ROLES:
        rpc(containers, role, "admin_addPeer", [enodes["M"]])

    observations: list[dict[str, Any]] = []
    deadline = time.time() + timeout
    ready = False
    while time.time() < deadline:
        heights = {role: block_number(containers, role) for role in ["M", *ACTIVE_ROLES]}
        syncing = {role: rpc(containers, role, "eth_syncing") for role in ACTIVE_ROLES}
        observed_peers = {role: sorted(peer_roles(containers, role)) for role in ACTIVE_ROLES}
        row = {
            "heights": heights,
            "syncing": syncing,
            "observed_peers": observed_peers,
        }
        observations.append(row)
        if (
            heights["M"] > 0
            and all(heights[role] >= max(1, heights["M"] - 1) for role in ACTIVE_ROLES)
            and all(syncing[role] is False for role in ACTIVE_ROLES)
            and all("M" in observed_peers[role] for role in ACTIVE_ROLES)
        ):
            ready = True
            break
        time.sleep(5)

    remove_all_peers(containers, enodes)
    return {
        "ready": ready,
        "observations": observations,
        "final_active_peers": {role: sorted(peer_roles(containers, role)) for role in ACTIVE_ROLES},
    }


def normalize(edge: tuple[str, str]) -> tuple[str, str]:
    a, b = edge
    return (a, b) if a <= b else (b, a)


def connect_edges(containers: dict[str, str], enodes: dict[str, str], edges: set[tuple[str, str]]) -> dict[str, list[str]]:
    for a, b in sorted(edges):
        rpc(containers, a, "admin_addPeer", [enodes[b]])
        rpc(containers, b, "admin_addPeer", [enodes[a]])
    deadline = time.time() + 45
    wanted = {role: set() for role in ACTIVE_ROLES}
    for a, b in edges:
        wanted[a].add(b)
        wanted[b].add(a)
    while time.time() < deadline:
        observed = {role: peer_roles(containers, role) & set(ACTIVE_ROLES) for role in ACTIVE_ROLES}
        if all(wanted[role] <= observed[role] for role in ACTIVE_ROLES):
            return {role: sorted(observed[role]) for role in ACTIVE_ROLES}
        time.sleep(0.25)
    return {role: sorted(peer_roles(containers, role) & set(ACTIVE_ROLES)) for role in ACTIVE_ROLES}


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


def send_raw(containers: dict[str, str], role: str, raw: str) -> str:
    return rpc(containers, role, "eth_sendRawTransaction", [raw])


def send_raw_batch(containers: dict[str, str], role: str, raws: list[str]) -> list[str]:
    if not raws:
        return []
    payload = json.dumps([
        {"jsonrpc": "2.0", "id": i, "method": "eth_sendRawTransaction", "params": [raw]}
        for i, raw in enumerate(raws)
    ])
    result = dexec(
        containers[role],
        "curl",
        "--max-time",
        "30",
        "-s",
        "-H",
        "Content-Type: application/json",
        "--data",
        payload,
        "http://127.0.0.1:8545",
        timeout=40,
        check=True,
    )
    data = json.loads(result["stdout"])
    by_id = {row["id"]: row for row in data}
    hashes: list[str] = []
    for i in range(len(raws)):
        row = by_id[i]
        if "error" in row:
            raise RuntimeError(f"RPC batch {role}.eth_sendRawTransaction failed at {i}: {row['error']}")
        hashes.append(row["result"])
    return hashes


def has_tx(containers: dict[str, str], role: str, tx_hash: str) -> bool:
    try:
        content = rpc(containers, role, "txpool_content", timeout=8)
    except Exception:
        return False
    wanted = tx_hash.lower()
    for section in ("pending", "queued"):
        accounts = content.get(section, {})
        for nonces in accounts.values():
            for tx in nonces.values():
                if isinstance(tx, dict) and tx.get("hash", "").lower() == wanted:
                    return True
    return False


def txpool_hashes(containers: dict[str, str], role: str) -> set[str]:
    content = rpc(containers, role, "txpool_content", timeout=20)
    hashes: set[str] = set()
    for section in ("pending", "queued"):
        accounts = content.get(section, {})
        for nonces in accounts.values():
            for tx in nonces.values():
                if isinstance(tx, dict) and tx.get("hash"):
                    hashes.add(tx["hash"].lower())
    return hashes


def prepare_iteration(containers: dict[str, str], account_start: int) -> list[TxFamily]:
    recipient = account(0).address
    families: list[TxFamily] = []
    next_account = account_start
    for source, sink in CANDIDATE_EDGES:
        blockers = [role for role in ACTIVE_ROLES if role not in (source, sink)]
        sender, raw_low, low_hash = signed_tx(next_account, GAS_LOW, recipient)
        _, raw_mid, mid_hash = signed_tx(next_account, GAS_MID, recipient)
        _, raw_high, high_hash = signed_tx(next_account, GAS_HIGH, recipient)
        for blocker in blockers:
            send_raw(containers, blocker, raw_mid)
        send_raw(containers, sink, raw_low)
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
    return families


def prepare_iteration_offline(account_start: int) -> tuple[list[TxFamily], dict[str, list[str]]]:
    recipient = account(0).address
    families: list[TxFamily] = []
    sends: dict[str, list[str]] = {role: [] for role in ACTIVE_ROLES}
    next_account = account_start
    for source, sink in CANDIDATE_EDGES:
        blockers = [role for role in ACTIVE_ROLES if role not in (source, sink)]
        sender, raw_low, low_hash = signed_tx(next_account, GAS_LOW, recipient)
        _, raw_mid, mid_hash = signed_tx(next_account, GAS_MID, recipient)
        _, raw_high, high_hash = signed_tx(next_account, GAS_HIGH, recipient)
        for blocker in blockers:
            sends[blocker].append(raw_mid)
        sends[sink].append(raw_low)
        sends[source].append(raw_high)
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


def measure_once(containers: dict[str, str], enodes: dict[str, str], truth_edges: set[tuple[str, str]], account_start: int) -> dict[str, Any]:
    remove_all_peers(containers, enodes)
    families = prepare_iteration(containers, account_start)
    for family in families:
        _, raw_high, _ = signed_tx(family.account_index, GAS_HIGH, account(0).address)
        send_raw(containers, family.source, raw_high)
    observed_peers = connect_edges(containers, enodes, truth_edges)
    time.sleep(1.5)
    inferred: list[tuple[str, str]] = []
    observations: list[dict[str, Any]] = []
    for family in families:
        present = has_tx(containers, family.sink, family.high_hash)
        edge = normalize((family.source, family.sink))
        if present:
            inferred.append(edge)
        observations.append({
            **asdict(family),
            "edge": list(edge),
            "high_tx_present_at_sink": present,
            "low_tx_present_at_sink": has_tx(containers, family.sink, family.low_hash),
            "mid_tx_present_at_blockers": {blocker: has_tx(containers, blocker, family.mid_hash) for blocker in family.blockers},
        })
    return {
        "ground_truth_edges": [list(edge) for edge in sorted(truth_edges)],
        "observed_peers": observed_peers,
        "inferred_edges": [list(edge) for edge in sorted(set(inferred))],
        "observations": observations,
    }


def measure_batch(containers: dict[str, str], enodes: dict[str, str], truth_edges: set[tuple[str, str]], account_start: int, iterations: int) -> list[dict[str, Any]]:
    remove_all_peers(containers, enodes)
    rows: list[dict[str, Any]] = []
    families_by_iteration: list[list[TxFamily]] = []
    sends_by_role: dict[str, list[str]] = {role: [] for role in ACTIVE_ROLES}
    for i in range(iterations):
        families, sends = prepare_iteration_offline(account_start + i * len(CANDIDATE_EDGES))
        for role, raws in sends.items():
            sends_by_role[role].extend(raws)
        families_by_iteration.append(families)

    for role, raws in sends_by_role.items():
        send_raw_batch(containers, role, raws)

    observed_peers = connect_edges(containers, enodes, truth_edges)
    time.sleep(max(3.0, min(15.0, iterations * 0.05)))
    hashes_by_role = {role: txpool_hashes(containers, role) for role in ACTIVE_ROLES}

    for i, families in enumerate(families_by_iteration):
        inferred: list[tuple[str, str]] = []
        observations: list[dict[str, Any]] = []
        for family in families:
            present = family.high_hash.lower() in hashes_by_role[family.sink]
            edge = normalize((family.source, family.sink))
            if present:
                inferred.append(edge)
            observations.append({
                **asdict(family),
                "edge": list(edge),
                "high_tx_present_at_sink": present,
                "low_tx_present_at_sink": family.low_hash.lower() in hashes_by_role[family.sink],
                "mid_tx_present_at_blockers": {blocker: family.mid_hash.lower() in hashes_by_role[blocker] for blocker in family.blockers},
            })
        rows.append({
            "ground_truth_edges": [list(edge) for edge in sorted(truth_edges)],
            "observed_peers": observed_peers,
            "inferred_edges": [list(edge) for edge in sorted(set(inferred))],
            "observations": observations,
            "iteration": i,
        })
    return rows


def precision_recall(truth: set[tuple[str, str]], predicted: set[tuple[str, str]]) -> tuple[float, float]:
    if not truth and not predicted:
        return 1.0, 1.0
    precision = 1.0 if not predicted else len(truth & predicted) / len(predicted)
    recall = 1.0 if not truth else len(truth & predicted) / len(truth)
    return round(precision, 6), round(recall, 6)


def run_case(containers: dict[str, str], enodes: dict[str, str], name: str, truth: set[tuple[str, str]], iterations: int, account_start: int) -> dict[str, Any]:
    iteration_rows = measure_batch(containers, enodes, truth, account_start, iterations)
    union_predicted: set[tuple[str, str]] = set()
    iteration_scores: list[tuple[float, float]] = []
    for row in iteration_rows:
        predicted = {tuple(edge) for edge in row["inferred_edges"]}
        union_predicted |= predicted
        row_precision, row_recall = precision_recall(truth, predicted)
        row["precision"] = row_precision
        row["recall"] = row_recall
        iteration_scores.append((row_precision, row_recall))
    precision = min(score[0] for score in iteration_scores)
    recall = min(score[1] for score in iteration_scores)
    return {
        "case": name,
        "ground_truth_edges": [list(edge) for edge in sorted(truth)],
        "iterations": iterations,
        "candidate_edges": [list(edge) for edge in CANDIDATE_EDGES],
        "inferred_edges": [list(edge) for edge in sorted(union_predicted)],
        "precision": precision,
        "recall": recall,
        "iteration_results": iteration_rows,
    }


def local_cases() -> list[tuple[str, set[tuple[str, str]]]]:
    e12 = normalize(("A1", "A2"))
    e1b = normalize(("A1", "B"))
    e2b = normalize(("A2", "B"))
    return [
        ("A1-A2, A1-B, A2-B", {e12, e1b, e2b}),
        ("A1-A2, A1-B", {e12, e1b}),
        ("A1-A2, A2-B", {e12, e2b}),
        ("A1-A2", {e12}),
        ("A1-B, A2-B", {e1b, e2b}),
        ("A1-B", {e1b}),
        ("Null", set()),
    ]


def parse_args():
    parser = argparse.ArgumentParser(description="Run TopoShot local parallel validation against live SEED/Geth nodes.")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--ready-timeout", type=int, default=120)
    parser.add_argument("--account-start", type=int, default=10)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent / "results" / "measurements.json"))
    parser.add_argument("--assert-success", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    containers = discover_containers()
    readiness = wait_for_rpc(containers, args.ready_timeout)
    if not readiness["ready"]:
        raise SystemExit(json.dumps({"containers": containers, "readiness": readiness}, indent=2))
    enodes = node_enodes(containers)
    chain_sync = sync_active_nodes_with_miner(containers, enodes, args.ready_timeout)
    if not chain_sync["ready"]:
        raise SystemExit(json.dumps({"containers": containers, "readiness": readiness, "chain_sync": chain_sync}, indent=2))
    cases: list[dict[str, Any]] = []
    next_account = args.account_start
    for name, truth in local_cases():
        case = run_case(containers, enodes, name, truth, args.iterations, next_account)
        cases.append(case)
        next_account += args.iterations * len(CANDIDATE_EDGES)
        print(f"case={name} precision={case['precision']:.3f} recall={case['recall']:.3f} inferred={case['inferred_edges']}")
    remove_all_peers(containers, enodes)
    payload = {
        "reference": "TopoShot: Uncovering Ethereum's Network Topology Leveraging Replacement Transactions",
        "reference_url": "https://doi.org/10.1145/3487552.3487814",
        "pdf_url": "https://tristartom.github.io/docs/imc21-toposhot.pdf",
        "experiment_description": "Local parallel topology probing with replacement transactions",
        "containers": containers,
        "role_ips": ROLE_IPS,
        "readiness": readiness,
        "chain_sync": chain_sync,
        "enodes": enodes,
        "parameters": {
            "iterations_per_case": args.iterations,
            "gas_price_low_txB": GAS_LOW,
            "gas_price_mid_txC": GAS_MID,
            "gas_price_high_txA": GAS_HIGH,
            "chain_id": CHAIN_ID,
            "account_start": args.account_start,
            "accounts_used": next_account - args.account_start,
        },
        "toposhot_runtime_adaptation": (
            "The driver checks local peer connections on controlled SEED/Geth nodes. "
            "For each candidate edge, it seeds 95%-priced txB at the sink, 100%-priced txC at blockers, and 105%-priced txA at the source while peers are disconnected, "
            "then reconnects the ground-truth overlay and observes which sinks receive txA. "
            "A direct source-sink edge is inferred when txA replaces txB at the sink; blockers reject txA because it is below Geth's default replacement price bump over txC."
        ),
        "cases": cases,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"wrote {args.output}")
    if args.assert_success:
        failures = [
            f"{case['case']} precision={case['precision']} recall={case['recall']}"
            for case in cases
            if case["precision"] != 1.0 or case["recall"] != 1.0
        ]
        if failures:
            raise AssertionError("; ".join(failures))
        print("PASS toposhot_runtime_parallel_validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
