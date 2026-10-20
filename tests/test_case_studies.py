"""Check attack evidence and sampled observations without a live deployment."""
import json
from types import SimpleNamespace

import pytest

from case_study.CS1_knockblock import run_attack as attack
from case_study.CS4_eth20_na import measure


@pytest.mark.parametrize('http_code,returncode,present', [
    ('200', 0, True), ('404', 0, False), ('500', 0, None), ('000', 28, None),
])
def test_slot_queries_distinguish_missing_blocks_from_failed_requests(monkeypatch, http_code, returncode, present):
    body = json.dumps({'data': {'message': {'proposer_index': '0', 'body': {}}}})
    monkeypatch.setattr(attack, 'dexec', lambda *a, **k: dict(stdout=body+'\n'+http_code, returncode=returncode))
    assert attack.query_slot(42)['present'] is present


def test_unknown_slots_and_total_ping_loss_are_not_success():
    evidence = dict(
        phases=[dict(phase='before', ping_victim_from_validator={'stdout': '100% packet loss'}),
                dict(phase='after', ping_victim_from_validator={'stdout': '100% packet loss'})],
        duties=[dict(slot=42, mapped_beacon_index=0)],
        slot_queries=[dict(slot=42, present=None)],
        selected_slots={'victim': {'slot': 42}},
    )
    analysis = attack.analyze(evidence, 2)
    assert not analysis['victim_reachability_before_ok']
    assert not analysis['victim_reachability_after_ok']
    assert not analysis['victim_slot_suppression_observed']
    assert not attack.successful_attack(analysis)


def test_success_requires_selected_slot_suppression_and_recovery():
    analysis = dict(route_hijack_observed=True, victim_reachability_before_ok=True,
                    victim_reachability_during_failed=True, victim_reachability_after_ok=True,
                    selected_victim_slot_present=False)
    assert attack.successful_attack(analysis)
    assert not attack.successful_attack(dict(analysis, selected_victim_slot_present=None))
    assert not attack.successful_attack(dict(analysis, victim_reachability_after_ok=False))


def test_head_spread_requires_all_beacons():
    beacons = [{'container': 'a'}, {'container': 'b'}]
    samples = [dict(t=1, slots={'a': {'slot': 1}, 'b': {'error': 'timeout'}}),
               dict(t=2, slots={'a': {'slot': 2}, 'b': {'slot': 1}}),
               dict(t=3, slots={'a': {'slot': 3}, 'b': {'error': 'timeout'}})]
    summary = measure.summarize_samples(samples, beacons)
    assert summary['complete_slot_count'] == 1
    assert summary['propagation_spread_seconds']['mean'] == 1
    assert summary['errors'] == 2
    empty = measure.summarize_samples([], beacons)
    assert empty['propagation_spread_seconds']['mean'] is None


def test_peer_count_mismatch_fails_before_network_queries(tmp_path, monkeypatch):
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps(dict(target_peers=7, beacons=[])))
    monkeypatch.setattr(measure, 'wait_for_beacons', lambda *a, **k: pytest.fail('network queried'))
    with pytest.raises(ValueError, match='target_peers'):
        measure.run_one(SimpleNamespace(manifest=manifest, target_peers=8))


def test_amplification_network_has_room_for_all_client_roles():
    from case_study.CS2_blockchain_amplification.build import build_emulator
    emu, roles = build_emulator(nodes=28, modified_count=0)
    systems = emu.getLayer('Base').getAsns()
    hosts = sum(len(emu.getLayer('Base').getAutonomousSystem(asn).getHosts()) for asn in systems)
    assert hosts >= len(roles)
