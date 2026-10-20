#!/usr/bin/env python3
"""Summarize one E12 trial without changing raw data or treating gaps as success."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics


def rows(path):
    if not path.exists():
        return []
    with path.open() as handle:
        return list(csv.DictReader(handle))


def stamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def percentile(values, quantile):
    values = sorted(values)
    if not values:
        return None
    position = (len(values)-1) * quantile
    index = int(position)
    return values[index] + (values[min(index+1, len(values)-1)] - values[index]) * (position-index)


def write_csv(path, records):
    with path.open('w', newline='') as handle:
        if records:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader(); writer.writerows(records)


def summarize(root, profile_path=None):
    cfg = json.loads((root / 'deployment.json' if (root / 'deployment.json').exists() else root / 'output/deployment.json').read_text())
    profile = json.loads(Path(profile_path or Path(__file__).parent/'profiles/paper_5_1.json').read_text())
    failures = []
    phases = rows(root / 'tx-load/tx_phases.csv')
    phase = next((r for r in phases if r['phase'] == 'steady'), None)
    if not phase:
        raise ValueError('No completed steady phase; retain raw data and investigate')
    start, end = stamp(phase['start_timestamp']), stamp(phase['end_timestamp'])
    duration = float(phase['configured_duration_sec'])
    if start is None or end is None or end <= start or duration <= 0:
        raise ValueError('Invalid measurement window')
    # Bound all scientific samples by the configured offered-load window.
    end = min(end, start + duration)
    def inside(row):
        timestamp = stamp(row.get('timestamp', ''))
        return timestamp is not None and start <= timestamp <= end
    grouped = defaultdict(list)
    for row in rows(root / 'memory_by_type.csv'):
        if inside(row):
            grouped[row['sample']].append(row)
    expected = {'beacon': cfg['beacons'], 'geth': cfg['geth'], 'validator': cfg['validator_clients']}
    series = []
    for sample, group in grouped.items():
        counts = {r['node_type']: int(r['containers']) for r in group}
        complete = all(counts.get(role) == count for role, count in expected.items())
        series.append(dict(sample=sample, timestamp=group[0]['timestamp'],
            elapsed_seconds=stamp(group[0]['timestamp'])-start, complete_roles=complete,
            memory_gib=sum(float(r['mem_total_bytes']) for r in group)/2**30,
            cpu_cores=sum(float(r['cpu_avg_percent'])*int(r['containers']) for r in group)/100))
        if not complete:
            failures.append('resource_role_count_mismatch')
        if any((number(r.get('memory_oom_kill_total')) or 0) > 0 for r in group):
            failures.append('container_oom_kill')
    valid = [r for r in series if r['complete_roles']]
    memory_coverage = min(100, len(valid)*60/duration*100)
    result = dict(beacons=cfg['beacons'], geth=cfg['geth'], validator_clients=cfg['validator_clients'],
        validators=cfg['active_validators'], duration_seconds=duration, target_tps=float(phase['target_rate']),
        memory_coverage_pct=memory_coverage)
    for field in ('memory_gib', 'cpu_cores'):
        # Collector round 1 has no CPU delta; never count it as measured CPU.
        values = [r[field] for r in valid if field != 'cpu_cores' or r['sample'] != '1']
        result[field+'_mean'] = statistics.mean(values) if values else None
        result[field+'_peak'] = max(values) if values else None
    health = []
    path = root / 'health/samples.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                if start <= row.get('time', 0) <= end:
                    health.append(row)
            except ValueError:
                failures.append('malformed_health_record')
    result['health_coverage_pct'] = min(100, len(health)*60/duration*100)
    result['healthy_round_pct'] = 100*sum(r.get('healthy', False) for r in health)/len(health) if health else None
    finality = [r for r in rows(root / 'consensus/finality_samples.csv') if inside(r) and not r['error']]
    epochs = [int(r['finalized_epoch']) for r in finality if r['finalized_epoch']]
    result['finalized_epoch_advance'] = epochs[-1]-epochs[0] if epochs else None
    result['finality_coverage_pct'] = min(100, len(finality)*12/duration*100)
    lags = [float(r['finality_lag']) for r in finality if number(r['finality_lag']) is not None]
    result['finality_lag_p95_epochs'] = percentile(lags, .95)
    activity = [float(r['participation_percent']) for r in rows(root/'consensus/validator_liveness.csv')
        if inside(r) and not r['error'] and number(r['participation_percent']) is not None
        and int(r['queried_validators']) == cfg['active_validators']]
    result['active_validators_mean_pct'] = statistics.mean(activity) if activity else None
    slots = {int(r['slot']): r for r in rows(root/'consensus/canonical_slot_observations.csv') if inside(r) and not r['error']}
    result['slot_coverage_pct'] = 100*len(slots)/(max(slots)-min(slots)+1) if slots else 0
    result['missed_slots_pct'] = 100*sum(r['canonical'] != '1' for r in slots.values())/len(slots) if slots else None
    blocks = {r['block_hash']: r for r in rows(root/'block_metrics.csv')
        if r['block_hash'] and number(r['block_time_unix']) is not None and start <= float(r['block_time_unix']) <= end}
    result['included_tps'] = sum(int(r['tx_count']) for r in blocks.values())/duration if blocks else None
    sent = failed = 0
    with (root/'tx-load/tx_sender.csv').open() as handle:
        for row in csv.DictReader(handle):
            sent += row['status'] == 'sent'
            failed += row['status'] != 'sent'
    result.update(sent=sent, send_failures=failed, sent_tps=sent/duration,
                  send_achievement_pct=100*sent/(duration*result['target_tps']))
    receipt_count = receipt_success = 0
    with (root/'tx_receipts.csv').open() as handle:
        for row in csv.DictReader(handle):
            receipt_count += 1
            receipt_success += row['status'] in ('1', '0x1')
    result.update(receipts=receipt_count, execution_successes=receipt_success,
                  final_inclusion_pct=100*receipt_count/sent if sent else None)
    def state(path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
    sender = state(root/'tx-load/run_info.json')
    receipts = state(root/'tx_receipts_run_info.json')
    if (sender.get('status') != 'complete' or sender.get('sent') != sent
            or receipts.get('status') != 'complete'
            or receipts.get('known_sent_transactions') != sent
            or receipts.get('pending_transactions') != 0
            or receipt_count != sent or receipt_success != sent or sent == 0):
        failures.append('transaction_completion_or_execution_failed')
    thresholds = profile['health']
    for field in ('memory_coverage_pct', 'health_coverage_pct', 'finality_coverage_pct', 'slot_coverage_pct'):
        if result[field] < thresholds['minimum_coverage_pct']:
            failures.append(field)
    for field in ('healthy_round_pct', 'send_achievement_pct'):
        threshold = thresholds['minimum_healthy_round_pct' if field == 'healthy_round_pct' else 'minimum_send_achievement_pct']
        if result[field] is None or result[field] < threshold:
            failures.append(field)
    if result['included_tps'] is None or result['included_tps'] / result['target_tps'] * 100 < thresholds['minimum_included_tps_achievement_pct']:
        failures.append('included_tps')
    if result['finalized_epoch_advance'] is None or result['finalized_epoch_advance'] <= 0:
        failures.append('finality_did_not_advance')
    if result['active_validators_mean_pct'] is None:
        failures.append('validator_activity_missing')
    for field, limit in [('finality_lag_p95_epochs', 'maximum_finality_lag_epochs'), ('missed_slots_pct', 'maximum_missed_slot_pct')]:
        if result[field] is None or result[field] > thresholds[limit]:
            failures.append(field)
    result.update(status='failed' if failures else 'passed', failure_reasons=sorted(set(failures)))
    target = root/'summary'
    target.mkdir(exist_ok=True)
    (target/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    write_csv(target/'result.csv', [result])
    write_csv(target/'resources.csv', series)
    for field, label in [('memory_gib', 'Container memory (GiB)'), ('cpu_cores', 'Container CPU (logical cores)')]:
        if not valid:
            continue
        maximum = max(r[field] for r in valid) or 1
        points = ' '.join(f'{60+r["elapsed_seconds"]/duration*700:.2f},{350-r[field]/maximum*270:.2f}' for r in valid)
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="420"><rect width="100%" height="100%" fill="white"/><text x="60" y="30">{label}; {result["status"]}</text><path d="M60 60V350H780" fill="none" stroke="black"/><polyline points="{points}" fill="none" stroke="#176ca4"/><text x="320" y="400">Seconds since workload start</text><text x="60" y="375">0</text><text x="730" y="375">{duration:g}</text><text x="5" y="85">{maximum:.1f}</text></svg>'
        (target/(field+'.svg')).write_text(svg)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--profile', type=Path, help='Optional JSON with summary health thresholds')
    a = p.parse_args()
    result = summarize(a.run_dir.resolve(), a.profile)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
