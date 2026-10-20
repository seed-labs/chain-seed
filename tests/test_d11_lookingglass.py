"""Check D11's test predicates reject missing, stale and configured-only data."""

import copy

import pytest

from examples.D11_lookingglass import ethereum_pos, test_runtime as checks
from chainseed.ethereum import LookingglassServer, PoSBeaconServer, PoSGethServer


@pytest.fixture
def observation():
    nodes = []
    for role in ('geth', 'beacon'):
        for index in range(2):
            node = dict(id=f'{role}{index}', role=role, asn=str(150 + index), chain='pos',
                        peer_probe=dict(at=1000, count=1, error=None),
                        metrics_checked_at=1000, metrics_error=None)
            if role == 'geth':
                node['txpool'] = dict(at=1000, pending=0, queued=0)
            else:
                node.update(head=4, head_at=1000, head_error=None)
            nodes.append(node)
    service_edges = [dict(source=f'beacon{i}', target=f'geth{i}', kind='service') for i in range(2)]
    inventory = dict(nodes=copy.deepcopy(nodes), edges=copy.deepcopy(service_edges))
    data = dict(mode='live', probe_active=True, nodes=nodes, edges=service_edges + [
        dict(source=f'{role}0', target=f'{role}1', kind='peer', at=1000, reported_by=[f'{role}0'])
        for role in ('geth', 'beacon')])
    return inventory, data


def test_complete_live_observations_pass(observation):
    inventory, data = observation
    assert checks.inventory_error(data, inventory) is None
    assert checks.dependency_error(inventory) is None
    assert checks.live_error(data, now=1000) is None
    assert checks.progress_error(data, {'beacon0': 3, 'beacon1': 3}) is None


def test_actual_probe_merge_exposes_metrics_freshness(observation, monkeypatch):
    from chainseed.ethereum.LookingglassServer import app
    _, data = observation
    geth = data['nodes'][0]
    geth['ip'] = '10.150.0.71'
    geth.pop('metrics_checked_at')
    geth.pop('txpool')
    data['capabilities'] = {}
    monkeypatch.setattr(app.time, 'time', lambda: 1000)
    monkeypatch.setattr(app, 'fetch', lambda *args, **kwargs: {'result': {'pending': '0x0', 'queued': '0x0'}})
    probe = app.PeerProbe([geth])
    probe.poll_metrics(geth)
    probe.merge(data)
    assert checks.live_error(data, now=1000) is None


@pytest.mark.parametrize('change', ['missing_node', 'duplicate_id', 'recorded_mode', 'wrong_dependency'])
def test_global_inventory_mismatches_fail(observation, change):
    inventory, data = observation
    if change == 'missing_node':
        data['nodes'].pop()
    elif change == 'duplicate_id':
        data['nodes'].append(copy.deepcopy(data['nodes'][0]))
    elif change == 'recorded_mode':
        data['mode'] = 'recorded'
    else:
        data['edges'][0]['target'] = 'geth1'
    assert checks.inventory_error(data, inventory)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'wrong_role'])
def test_compiled_inventory_must_include_valid_dependencies(observation, change):
    inventory, _ = observation
    if change == 'missing':
        inventory['edges'].pop()
    elif change == 'duplicate':
        inventory['edges'].append(copy.deepcopy(inventory['edges'][0]))
    else:
        inventory['edges'][0]['target'] = 'beacon1'
    assert checks.dependency_error(inventory)


@pytest.mark.parametrize('change', ['stale_peer', 'no_peers', 'no_metrics_query', 'metrics_failed',
                                   'stale_head', 'no_txpool', 'configured_only', 'no_cross_as'])
def test_incomplete_runtime_observations_fail(observation, change):
    _, data = observation
    geth, beacon = data['nodes'][0], data['nodes'][2]
    if change == 'stale_peer':
        geth['peer_probe']['at'] = 900
    elif change == 'no_peers':
        geth['peer_probe']['count'] = 0
    elif change == 'no_metrics_query':
        beacon.pop('metrics_checked_at')
    elif change == 'metrics_failed':
        beacon['metrics_error'] = 'connection refused'
    elif change == 'stale_head':
        beacon['head_at'] = 900
    elif change == 'no_txpool':
        geth.pop('txpool')
    elif change == 'configured_only':
        data['edges'] = [edge for edge in data['edges'] if edge['kind'] == 'service']
    else:
        for node in data['nodes']:
            node['asn'] = '150'
    assert checks.live_error(data, now=1000)


def test_stalled_or_missing_head_cannot_pass_progress_check(observation):
    _, data = observation
    assert checks.progress_error(data, {'beacon0': 4})
    assert checks.progress_error(data, {'unknown': 3})
    assert checks.progress_error(data, {})
    data['nodes'][2]['head'] = None
    assert checks.progress_error(data, {'beacon0': 3})


def test_polling_failure_is_recorded_without_docker(monkeypatch, tmp_path):
    from types import SimpleNamespace
    test = SimpleNamespace(results=[], artifact_dir=tmp_path)

    def unavailable(path):
        raise OSError('host port unavailable')

    monkeypatch.setattr(checks, 'fetch', unavailable)
    assert checks.wait_json(test, 'host access', '/api/snapshot', lambda data: None, retries=1) is None
    assert test.results[0]['status'] == 'failed'
    assert 'host port unavailable' in test.results[0]['stdout']


def test_slow_http_cannot_extend_the_polling_budget(monkeypatch, tmp_path):
    from types import SimpleNamespace
    test = SimpleNamespace(results=[], artifact_dir=tmp_path)
    clock = iter((0, 11))
    monkeypatch.setattr(checks.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(checks, 'fetch', lambda path: (200, '{}'))
    calls = []
    monkeypatch.setattr(checks.time, 'sleep', lambda seconds: calls.append(seconds))
    assert checks.wait_json(test, 'timeout', '/api/snapshot', lambda data: 'not ready', retries=2) is None
    assert test.results[0]['status'] == 'failed' and not calls


def test_d11_enables_client_apis_but_keeps_viewer_defaults():
    emu = ethereum_pos.build_emulator()
    targets = emu.getLayer('EthereumService').getPendingTargets()
    viewer = targets['lookingglass']
    assert isinstance(viewer, LookingglassServer) and viewer.getPort() == 8765
    beacons = [server for server in targets.values() if isinstance(server, PoSBeaconServer)]
    geth = [server for server in targets.values() if isinstance(server, PoSGethServer)]
    assert len(beacons) == len(geth) == 3
    assert all(server.getMetricsPort() == 5054 for server in beacons)
    assert all(server.isGethHttpEnabled() for server in geth)
