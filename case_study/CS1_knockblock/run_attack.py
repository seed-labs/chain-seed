#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"

ATTACKER_CONTAINER = "as230h-ExaBGP_Control_Plane_Speaker-10.100.0.230"
OBSERVER_ROUTER = "as205brd-router0-10.205.0.254"
OBSERVER_HOST = "as205h-Routing-POS-Validator-0-10.205.0.71"
VICTIM_BEACON_IP = "10.203.0.71"
VICTIM_PREFIX = "10.203.0.0/25"
BEACON_API = f"http://{VICTIM_BEACON_IP}:8000"
SLOTS_PER_EPOCH_FALLBACK = 32
SECONDS_PER_SLOT_FALLBACK = 12


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 30, check: bool = False) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
    out = {
        "cmd": cmd,
        "cwd": str(cwd) if cwd else None,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if check and proc.returncode:
        raise RuntimeError(json.dumps(out, indent=2))
    return out


def compose(output_dir: Path, *args: str, timeout: int = 120, check: bool = False) -> dict[str, Any]:
    return run(["docker", "compose", *args], cwd=output_dir, timeout=timeout, check=check)


def dexec(container: str, *args: str, timeout: int = 15, check: bool = False) -> dict[str, Any]:
    return run(["docker", "exec", container, *args], timeout=timeout, check=check)


def docker_logs(container: str, *, tail: int = 500) -> dict[str, Any]:
    return run(["docker", "logs", "--tail", str(tail), container], timeout=30)


def curl_json(container: str, url: str, timeout_seconds: int = 4) -> Any | None:
    res = dexec(container, "curl", "--max-time", str(timeout_seconds), "-s", url, timeout=timeout_seconds + 5)
    if res["returncode"]:
        return None
    try:
        return json.loads(res["stdout"])
    except Exception:
        return None


def curl_code(container: str, url: str, timeout_seconds: int = 4) -> dict[str, Any]:
    return dexec(
        container,
        "curl",
        "--max-time",
        str(timeout_seconds),
        "-s",
        "-o",
        "/tmp/knockblock_probe.out",
        "-w",
        "%{http_code}",
        url,
        timeout=timeout_seconds + 5,
    )


def list_containers() -> list[str]:
    res = run(["docker", "ps", "--format", "{{.Names}}"], timeout=20, check=True)
    return sorted([line.strip() for line in res["stdout"].splitlines() if line.strip()])


def find_container(pattern: str, containers: list[str]) -> str | None:
    for name in containers:
        if pattern in name:
            return name
    return None


def bind_runtime_container_names(containers: list[str]) -> dict[str, str]:
    global ATTACKER_CONTAINER, OBSERVER_ROUTER, OBSERVER_HOST
    attacker = find_container("ExaBGP_Control_Plane_Speaker", containers) or ATTACKER_CONTAINER
    router = find_container("as205brd-router0", containers) or OBSERVER_ROUTER
    observer = find_container("as205h-Routing-POS-Validator", containers)
    if observer is None:
        observer = find_container("as205h-Routing-POS-Beacon", containers)
    if observer is None:
        observer = OBSERVER_HOST
    ATTACKER_CONTAINER = attacker
    OBSERVER_ROUTER = router
    OBSERVER_HOST = observer
    return {"attacker_container": attacker, "observer_router": router, "observer_host": observer}


def head_slot(container: str = OBSERVER_HOST) -> int | None:
    data = curl_json(container, f"{BEACON_API}/eth/v1/beacon/headers/head", timeout_seconds=4)
    try:
        return int(data["data"]["header"]["message"]["slot"])
    except Exception:
        return None


def get_spec(container: str = OBSERVER_HOST) -> dict[str, Any]:
    data = curl_json(container, f"{BEACON_API}/eth/v1/config/spec", timeout_seconds=4) or {}
    spec = data.get("data", {}) if isinstance(data, dict) else {}
    out = {
        "SECONDS_PER_SLOT": int(spec.get("SECONDS_PER_SLOT", SECONDS_PER_SLOT_FALLBACK)),
        "SLOTS_PER_EPOCH": int(spec.get("SLOTS_PER_EPOCH", SLOTS_PER_EPOCH_FALLBACK)),
    }
    return out


def get_proposer_duties(epoch: int, container: str = OBSERVER_HOST) -> list[dict[str, Any]]:
    data = curl_json(container, f"{BEACON_API}/eth/v1/validator/duties/proposer/{epoch}", timeout_seconds=6)
    rows = []
    for row in (data or {}).get("data", []) if isinstance(data, dict) else []:
        try:
            rows.append({
                "epoch": epoch,
                "slot": int(row["slot"]),
                "validator_index": int(row["validator_index"]),
                "pubkey": row.get("pubkey"),
            })
        except Exception:
            pass
    return rows


def annotate_duties(rows: list[dict[str, Any]], beacon_nodes: int) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["mapped_beacon_index"] = item["validator_index"] % beacon_nodes
        item["role"] = "victim" if item["mapped_beacon_index"] == 0 else "attacker_or_control"
        out.append(item)
    return out


def collect_duties_around(current_slot: int, slots_per_epoch: int, beacon_nodes: int, epochs_ahead: int = 3) -> list[dict[str, Any]]:
    current_epoch = current_slot // slots_per_epoch
    rows: list[dict[str, Any]] = []
    for epoch in range(current_epoch, current_epoch + epochs_ahead + 1):
        rows.extend(get_proposer_duties(epoch))
    return annotate_duties(sorted(rows, key=lambda r: r["slot"]), beacon_nodes)


def capture_phase(name: str) -> dict[str, Any]:
    phase = {
        "phase": name,
        "timestamp_utc": utc_now(),
        "route_to_victim": dexec(OBSERVER_ROUTER, "birdc", "show", "route", "for", VICTIM_BEACON_IP, timeout=10),
        "ping_victim_from_validator": dexec(OBSERVER_HOST, "ping", "-c", "3", "-W", "1", VICTIM_BEACON_IP, timeout=8),
        "beacon_health_from_validator": curl_code(OBSERVER_HOST, f"{BEACON_API}/eth/v1/node/health", timeout_seconds=3),
        "beacon_head_from_validator": dexec(OBSERVER_HOST, "curl", "--max-time", "4", "-s", f"{BEACON_API}/eth/v1/beacon/headers/head", timeout=9),
        "head_slot_from_observer": head_slot(OBSERVER_HOST),
    }
    return phase


def query_slot(slot: int) -> dict[str, Any]:
    res = dexec(
        OBSERVER_HOST,
        "curl",
        "--max-time",
        "4",
        "-s",
        "-w",
        "\n%{http_code}",
        f"{BEACON_API}/eth/v2/beacon/blocks/{slot}",
        timeout=10,
    )
    body, _, code = res["stdout"].rpartition("\n")
    row: dict[str, Any] = {
        "slot": slot,
        "http_code": code.strip(),
        "present": (code.strip().startswith("2") if res["returncode"] == 0 and (code.strip().startswith("2") or code.strip() == "404") else None),
        "raw_result": res,
    }
    if row["present"]:
        try:
            block = json.loads(body)
            msg = block.get("data", {}).get("message", {})
            body_obj = msg.get("body", {})
            execution_payload = body_obj.get("execution_payload", {})
            row.update({
                "root": block.get("data", {}).get("root"),
                "proposer_index": int(msg.get("proposer_index")) if msg.get("proposer_index") is not None else None,
                "parent_root": msg.get("parent_root"),
                "state_root": msg.get("state_root"),
                "body_root": msg.get("body_root"),
                "execution_block_hash": execution_payload.get("block_hash"),
                "execution_parent_hash": execution_payload.get("parent_hash"),
                "execution_transactions_count": len(execution_payload.get("transactions", []) or []),
            })
        except Exception as exc:
            row["parse_error"] = str(exc)
            row["present"] = None
    return row


def wait_for_chain(max_seconds: int = 900, min_slot: int = 3) -> dict[str, Any]:
    observations = []
    last_slot = None
    advancing = 0
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        phase = capture_phase("readiness_probe")
        slot = phase.get("head_slot_from_observer")
        observations.append({
            "timestamp_utc": phase["timestamp_utc"],
            "slot": slot,
            "health_code": (phase["beacon_health_from_validator"].get("stdout") or "").strip(),
            "ping_returncode": phase["ping_victim_from_validator"].get("returncode"),
        })
        if isinstance(slot, int):
            if last_slot is not None and slot > last_slot:
                advancing += 1
            last_slot = slot
            if slot >= min_slot and advancing >= 1 and str((phase["beacon_health_from_validator"].get("stdout") or "")).strip() in {"200", "206"}:
                return {"ready": True, "slot": slot, "observations": observations}
        time.sleep(8)
    return {"ready": False, "slot": last_slot, "observations": observations}


def select_victim_slot(duties: list[dict[str, Any]], current_slot: int, lead_slots: int, beacon_nodes: int) -> dict[str, Any] | None:
    future = [d for d in duties if d["slot"] >= current_slot + lead_slots]
    victims = [d for d in future if d["mapped_beacon_index"] == 0]
    if not victims:
        return None
    for victim in victims:
        following = [d for d in duties if d["slot"] > victim["slot"] and d["slot"] <= victim["slot"] + 4 and d["mapped_beacon_index"] != 0]
        if following:
            return {"victim": victim, "attacker_or_control": following[0]}
    victim = victims[0]
    following = [d for d in duties if d["slot"] > victim["slot"] and d["mapped_beacon_index"] != 0]
    return {"victim": victim, "attacker_or_control": following[0] if following else None}


def route_selected_attacker(route_text: str) -> str | None:
    if "AS230" in route_text:
        return "AS230"
    if "AS203" in route_text:
        return "AS203"
    return None


def ping_loss(ping_text: str) -> bool:
    return "100% packet loss" in ping_text or " 0 received" in ping_text


def analyze(evidence: dict[str, Any], beacon_nodes: int) -> dict[str, Any]:
    phases = {p["phase"]: p for p in evidence.get("phases", [])}
    before = phases.get("before", {})
    during = phases.get("during", {})
    after = phases.get("after", {})
    before_route = before.get("route_to_victim", {}).get("stdout", "")
    during_route = during.get("route_to_victim", {}).get("stdout", "")
    after_route = after.get("route_to_victim", {}).get("stdout", "")
    before_ping = before.get("ping_victim_from_validator", {}).get("stdout", "")
    during_ping = during.get("ping_victim_from_validator", {}).get("stdout", "")
    after_ping = after.get("ping_victim_from_validator", {}).get("stdout", "")
    duty_by_slot = {d["slot"]: d for d in evidence.get("duties", [])}
    slots = evidence.get("slot_queries", [])
    for row in slots:
        duty = duty_by_slot.get(row["slot"])
        if duty:
            row["duty"] = duty
            if row.get("proposer_index") is not None:
                row["observed_mapped_beacon_index"] = int(row["proposer_index"]) % beacon_nodes
    victim = evidence.get("selected_slots", {}).get("victim") or {}
    attacker = evidence.get("selected_slots", {}).get("attacker_or_control") or {}
    victim_slot_query = next((r for r in slots if r["slot"] == victim.get("slot")), None)
    attacker_slot_query = next((r for r in slots if r["slot"] == attacker.get("slot")), None) if attacker else None
    missed_victim_slots = [r for r in slots if (r.get("duty", {}).get("mapped_beacon_index") == 0 and r.get("present") is False)]
    present_non_victim_after = [r for r in slots if (r.get("duty", {}).get("mapped_beacon_index") not in (None, 0) and r.get("present") and r["slot"] > (victim.get("slot") or -1))]
    return {
        "route_before_selected_as": route_selected_attacker(before_route),
        "route_during_selected_as": route_selected_attacker(during_route),
        "route_after_selected_as": route_selected_attacker(after_route),
        "route_hijack_observed": "AS203" in before_route and "AS230" in during_route and "AS203" in after_route,
        "victim_reachability_before_ok": bool(re.search(r"(?<!\d)0% packet loss", before_ping)),
        "victim_reachability_during_failed": ping_loss(during_ping),
        "victim_reachability_after_ok": bool(re.search(r"(?<!\d)0% packet loss", after_ping)),
        "selected_victim_slot": victim,
        "selected_attacker_or_control_slot": attacker,
        "selected_victim_slot_present": victim_slot_query.get("present") if victim_slot_query else None,
        "selected_attacker_or_control_slot_present": attacker_slot_query.get("present") if attacker_slot_query else None,
        "missed_victim_controlled_slots": missed_victim_slots,
        "present_non_victim_slots_after_victim": present_non_victim_after,
        "victim_slot_suppression_observed": bool(missed_victim_slots),
        "attacker_or_control_block_after_victim_observed": bool(present_non_victim_after),
    }


def successful_attack(analysis: dict[str, Any]) -> bool:
    return all(analysis.get(key) for key in (
        "route_hijack_observed", "victim_reachability_before_ok",
        "victim_reachability_during_failed", "victim_reachability_after_ok",
    )) and analysis.get("selected_victim_slot_present") is False


def write_report(path: Path, evidence: dict[str, Any]) -> None:
    a = evidence.get("analysis", {})
    selected = evidence.get("selected_slots", {})
    victim = selected.get("victim") or {}
    attacker = selected.get("attacker_or_control") or {}
    artifacts = evidence.get("artifacts", {})
    lines = [
        "# KnockBlock routing attack report",
        "",
        "## Summary",
        "",
        f"- Started: `{evidence.get('started_at_utc')}`",
        f"- Finished: `{evidence.get('finished_at_utc')}`",
        f"- Victim prefix: `{evidence.get('attack', {}).get('announced_prefix')}`",
        f"- Victim beacon endpoint: `{VICTIM_BEACON_IP}`",
        f"- Selected victim slot: `{victim.get('slot')}` proposer `{victim.get('validator_index')}` mapped to beacon `{victim.get('mapped_beacon_index')}`",
        f"- Selected attacker/control slot: `{attacker.get('slot')}` proposer `{attacker.get('validator_index')}` mapped to beacon `{attacker.get('mapped_beacon_index')}`",
        "",
        "## Result flags",
        "",
        f"- Route hijack observed: `{a.get('route_hijack_observed')}`",
        f"- Victim reachability failed during hijack: `{a.get('victim_reachability_during_failed')}`",
        f"- Victim-controlled missed slot observed: `{a.get('victim_slot_suppression_observed')}`",
        f"- Non-victim attacker/control block after victim observed: `{a.get('attacker_or_control_block_after_victim_observed')}`",
        f"- Selected victim slot present: `{a.get('selected_victim_slot_present')}`",
        f"- Selected attacker/control slot present: `{a.get('selected_attacker_or_control_slot_present')}`",
        "",
        "## Route evidence",
        "",
        f"- Before selected AS: `{a.get('route_before_selected_as')}`",
        f"- During selected AS: `{a.get('route_during_selected_as')}`",
        f"- After selected AS: `{a.get('route_after_selected_as')}`",
        "",
        "## Slot observations",
        "",
        "| slot | present | proposer | mapped beacon | role | execution block hash | tx count |",
        "| ---: | --- | ---: | ---: | --- | --- | ---: |",
    ]
    for row in evidence.get("slot_queries", []):
        d = row.get("duty", {})
        lines.append(
            f"| {row.get('slot')} | {row.get('present')} | {d.get('validator_index', row.get('proposer_index'))} | {d.get('mapped_beacon_index', row.get('observed_mapped_beacon_index'))} | {d.get('role', '')} | {row.get('execution_block_hash', '')} | {row.get('execution_transactions_count', '')} |"
        )
    lines += [
        "",
        "## Retained artifacts",
        "",
    ]
    for key, val in artifacts.items():
        lines.append(f"- {key}: `{val}`")
    lines += [
        "",
        "## Collected observations",
        "",
        "The saved data includes route selection, reachability, proposer duties, block queries and client logs. Compare observations before, during and after the announcement to assess its effect on the selected proposal and connectivity recovery.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_artifacts(artifacts_dir: Path, containers: list[str], evidence: dict[str, Any], output_dir: Path) -> dict[str, str]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = artifacts_dir / "docker_logs"
    logs_dir.mkdir(exist_ok=True)
    keep_patterns = ["Routing-POS-Beacon", "Routing-POS-Geth", "Routing-POS-Validator", "ExaBGP", "router0"]
    kept = []
    for name in containers:
        if any(pat in name for pat in keep_patterns):
            res = docker_logs(name, tail=1200)
            log_path = logs_dir / f"{safe_name(name)}.log"
            log_path.write_text(
                "# STDOUT\n" + res.get("stdout", "") + "\n# STDERR\n" + res.get("stderr", ""),
                encoding="utf-8",
            )
            kept.append(str(log_path))
    (artifacts_dir / "docker_ps.txt").write_text(run(["docker", "ps", "-a"], timeout=20).get("stdout", ""), encoding="utf-8")
    (artifacts_dir / "docker_networks.txt").write_text(run(["docker", "network", "ls"], timeout=20).get("stdout", ""), encoding="utf-8")
    if (output_dir / "docker-compose.yml").exists():
        shutil.copy2(output_dir / "docker-compose.yml", artifacts_dir / "docker-compose.yml")
    (artifacts_dir / "phases_pretty.json").write_text(json.dumps(evidence.get("phases", []), indent=2, sort_keys=True), encoding="utf-8")
    (artifacts_dir / "slot_queries_pretty.json").write_text(json.dumps(evidence.get("slot_queries", []), indent=2, sort_keys=True), encoding="utf-8")
    return {
        "artifacts_dir": str(artifacts_dir),
        "docker_logs_dir": str(logs_dir),
        "docker_log_files_count": str(len(kept)),
        "docker_compose_yml": str(artifacts_dir / "docker-compose.yml"),
        "docker_ps": str(artifacts_dir / "docker_ps.txt"),
        "phase_json": str(artifacts_dir / "phases_pretty.json"),
        "slot_queries_json": str(artifacts_dir / "slot_queries_pretty.json"),
    }


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir).resolve()
    if not (output_dir / "docker-compose.yml").is_file():
        raise FileNotFoundError("Compile with build.py and start Docker Compose first")
    evidence: dict[str, Any] = {
        "experiment": "knockblock_end_to_end",
        "started_at_utc": utc_now(),
        "commands": {},
        "attack": {
            "announced_prefix": args.prefix,
            "attacker_container": ATTACKER_CONTAINER,
            "observer_router": OBSERVER_ROUTER,
            "observer_host": OBSERVER_HOST,
            "victim_beacon_ip": VICTIM_BEACON_IP,
            "beacon_api": BEACON_API,
            "duration_seconds": args.duration,
        },
        "parameters": vars(args),
    }
    time.sleep(3)
    evidence["runtime_containers"] = bind_runtime_container_names(list_containers())
    evidence["attack"].update(evidence["runtime_containers"])
    readiness = wait_for_chain(max_seconds=args.ready_timeout, min_slot=args.min_ready_slot)
    evidence["readiness"] = readiness
    if not readiness.get("ready"):
        evidence["finished_at_utc"] = utc_now()
        evidence["ready"] = False
        return evidence
    evidence["ready"] = True
    spec = get_spec()
    evidence["spec"] = spec
    current = head_slot() or readiness.get("slot") or 0
    duties = collect_duties_around(current, spec["SLOTS_PER_EPOCH"], args.beacon_nodes, epochs_ahead=args.epochs_ahead)
    evidence["duties"] = duties
    selected = select_victim_slot(duties, current, args.lead_slots, args.beacon_nodes)
    evidence["selected_slots"] = selected or {}
    if not selected:
        evidence["finished_at_utc"] = utc_now()
        evidence["error"] = "no future victim beacon0 proposer slot found in sampled duties"
        return evidence
    target_slot = int(selected["victim"]["slot"])
    wait_observations = []
    while True:
        slot = head_slot()
        wait_observations.append({"timestamp_utc": utc_now(), "slot": slot})
        if slot is not None and slot >= target_slot - args.attack_start_lead_slots:
            break
        if slot is not None and slot > target_slot + 1:
            break
        time.sleep(min(4, max(1, spec["SECONDS_PER_SLOT"] // 3)))
    evidence["pre_attack_wait"] = wait_observations

    evidence.setdefault("phases", []).append(capture_phase("before"))
    attack_proc = subprocess.Popen(
        ["docker", "exec", ATTACKER_CONTAINER, "/root/knockblock_hijack.sh", args.prefix, str(args.duration)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(args.propagation_wait)
    evidence["phases"].append(capture_phase("during"))
    stdout, stderr = attack_proc.communicate(timeout=args.duration + 30)
    evidence["attack_process"] = {"returncode": attack_proc.returncode, "stdout": stdout, "stderr": stderr}
    time.sleep(args.recovery_wait)
    evidence["phases"].append(capture_phase("after"))

    latest = head_slot() or target_slot
    first_slot = max(0, min(target_slot - 3, int(evidence["phases"][0].get("head_slot_from_observer") or target_slot) - 1))
    # A 404 is meaningful only for elapsed slots, never for a future proposal.
    desired_slot = target_slot + args.post_slots
    deadline = time.monotonic() + (args.post_slots + 2) * spec["SECONDS_PER_SLOT"]
    while latest < desired_slot and time.monotonic() < deadline:
        time.sleep(min(4, spec["SECONDS_PER_SLOT"]))
        latest = head_slot() or latest
    last_slot = latest
    evidence["slot_query_range"] = {"first": first_slot, "last": last_slot}
    evidence["slot_queries"] = [query_slot(slot) for slot in range(first_slot, last_slot + 1)]
    evidence["analysis"] = analyze(evidence, args.beacon_nodes)
    evidence["finished_at_utc"] = utc_now()
    containers = list_containers()
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifacts_dir = RESULTS_DIR / f"knockblock_end_to_end_artifacts_{timestamp}"
    evidence["artifacts"] = save_artifacts(artifacts_dir, containers, evidence, output_dir)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a KnockBlock routing attack and save observations.")
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--beacon-nodes", type=int, default=8)
    parser.add_argument("--validators-per-beacon", type=int, default=4)
    parser.add_argument("--prefix", default=VICTIM_PREFIX)
    parser.add_argument("--duration", type=int, default=48)
    parser.add_argument("--propagation-wait", type=int, default=8)
    parser.add_argument("--recovery-wait", type=int, default=24)
    parser.add_argument("--lead-slots", type=int, default=4)
    parser.add_argument("--attack-start-lead-slots", type=int, default=1)
    parser.add_argument("--post-slots", type=int, default=8)
    parser.add_argument("--epochs-ahead", type=int, default=4)
    parser.add_argument("--min-ready-slot", type=int, default=3)
    parser.add_argument("--ready-timeout", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = run_experiment(args)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / "knockblock_end_to_end.json"
    report_path = RESULTS_DIR / "knockblock_end_to_end_report.md"
    json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    if evidence.get("ready"):
        write_report(report_path, evidence)
    print(json.dumps({
        "ready": evidence.get("ready"),
        "analysis": evidence.get("analysis"),
        "json": str(json_path.resolve()),
        "report": str(report_path.resolve()) if report_path.exists() else None,
        "artifacts": evidence.get("artifacts"),
        "error": evidence.get("error"),
    }, indent=2, sort_keys=True))
    return 0 if evidence.get("ready") and successful_attack(evidence.get("analysis", {})) else 2


if __name__ == "__main__":
    raise SystemExit(main())
