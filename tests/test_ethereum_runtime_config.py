"""Verify Server APIs through rendered files, compiled output and process argv."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml

from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService
from seedemu.core import Action, Binding, Emulator, Filter
from seedemu.layers import Base, Routing


MNEMONIC = 'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about'


@pytest.fixture
def network():
    names = ('g0', 'g1', 'g2', 'b0', 'b1', 'v0', 'v1', 'v2', 'setup')
    emu = Emulator()
    base = Base()
    system = base.createAutonomousSystem(150)
    system.createNetwork('net0')
    system.createRouter('router0').joinNetwork('net0')
    for name in names:
        system.createHost(name).joinNetwork('net0')
        emu.addBinding(Binding(name, action=Action.FIRST,
                               filter=Filter(asn=150, nodeName=f'^{name}$')))
    emu.addLayer(base)
    emu.addLayer(Routing())
    eth = EthereumService()
    chain = eth.createBlockchain('pos', ConsensusMechanism.POS)
    servers = {name: chain.createGethNode(name) for name in ('g0', 'g1', 'g2')}
    for index in range(2):
        name = f'b{index}'
        servers[name] = chain.createBeaconNode(name).setBootNode(True).connectToGethNode(f'g{index}')
    for index in range(3):
        name = f'v{index}'
        servers[name] = chain.createVcNode(name).enablePOSValidatorAtGenesis().connectToBeaconNode('b0')
    servers['setup'] = chain.createBeaconSetupNode('setup')
    emu.addLayer(eth)
    return emu, system, chain, servers


def content(host, path):
    return host.getFile(path).get()[1]


def starts(host):
    return '\n'.join(command for command, _ in host.getStartCommands())


def test_distinct_clients_reach_compiled_scripts_and_processes(network, tmp_path):
    emu, system, chain, servers = network
    servers['g0'].enableGethHttp().setCacheMiB(128).setGoMemoryLimitMiB(384).setRpcTxFeeCap(0)
    servers['g1'].setCacheMiB(256).setGoMemoryLimitMiB(512).setRpcTxFeeCap('0.5')
    servers['g2'].setCustomGethCommandOption('--maxpeers 12')
    servers['b0'].setProcessorMaxWorkers(2).setReconstructHistoricStates(False).enableMetrics(port=5055)
    servers['b0'].setBootstrapRetryPolicy(attempts=720, interval_seconds=1,
        connect_timeout_seconds=5, request_timeout_seconds=120)
    servers['b1'].setProcessorMaxWorkers(8).enableMetrics().enableMetrics(False)
    servers['v0'].setValidatorKeyCount(2)
    servers['v1'].setValidatorKeyCount(3)
    servers['setup'].setGenesisDelay(1800).setValidatorMnemonic(MNEMONIC)
    system.createHost('lookingglass').joinNetwork('net0')
    emu.addBinding(Binding('lookingglass', action=Action.FIRST,
                           filter=Filter(asn=150, nodeName='^lookingglass$')))
    emu.getLayer('EthereumService').createLookingglassServer()
    emu.render()

    # Run the generated Geth commands against an argv/env recorder. This proves
    # shell quoting and process-local GOMEMLIMIT, without requiring Docker/Geth.
    recorder = tmp_path / 'geth'
    recorder.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
        'print(json.dumps(dict(argv=sys.argv[1:], memory=os.getenv("GOMEMLIMIT"))))\n')
    recorder.chmod(0o755)
    cat = tmp_path / 'cat'
    cat.write_text('#!/bin/sh\nprintf "enode://fixture"\n')
    cat.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}:' + os.environ['PATH'])
    env.pop('GOMEMLIMIT', None)
    for name, cache, memory, fee in [('g0', '128', '384MiB', '0'), ('g1', '256', '512MiB', '0.5'), ('g2', None, None, None)]:
        command = next(command for command, _ in system.getHost(name).getStartCommands()
                       if command.startswith(('geth --datadir', 'env GOMEMLIMIT=')))
        actual = json.loads(subprocess.check_output(['bash', '-c', command], env=env, text=True))
        assert actual['memory'] == memory
        if cache is None:
            assert '--cache' not in actual['argv']
            assert '--rpc.txfeecap' not in actual['argv']
            assert actual['argv'][actual['argv'].index('--maxpeers')+1] == '12'
        else:
            assert actual['argv'][actual['argv'].index('--cache')+1] == cache
            assert actual['argv'][actual['argv'].index('--rpc.txfeecap')+1] == fee

    b0 = content(system.getHost('b0'), '/tmp/beacon-bootstrapper')
    b1 = content(system.getHost('b1'), '/tmp/beacon-bootstrapper')
    assert '--beacon-processor-max-workers 2' in b0
    assert '--reconstruct-historic-states' not in b0
    assert '--metrics-port 5055' in b0
    assert '--beacon-processor-max-workers 8' in b1
    assert '--reconstruct-historic-states' in b1
    assert '--metrics' not in b1
    assert '--connect-timeout 5 --max-time 120' in b0
    assert '[ $count -ge 720 ]' in b0
    assert '[ $count -ge 60 ]' in b1
    assert '--connect-timeout' not in b1
    g0_ip = system.getHost('g0').getInterfaces()[0].getAddress()
    assert f'--execution-endpoint http://{g0_ip}:8551' in b0
    assert 'GENESIS_TIME=$(( $(date +%s) + 1800 ))' in starts(system.getHost('setup'))

    mnemonics = yaml.safe_load(content(system.getHost('setup'), '/tmp/mnemonic.yaml'))
    assert [(entry['start'], entry['count']) for entry in mnemonics] == [(0, 2), (2, 3), (5, 1)]
    for name, entry in zip(('v0', 'v1', 'v2'), mnemonics):
        script = content(system.getHost(name), '/tmp/vc_bootstrapper')
        command = next(line.strip() for line in script.splitlines() if line.strip().startswith('eth2-val-tools keystores'))
        argv = shlex.split(command)
        assert int(argv[argv.index('--source-min')+1]) == entry['start']
        assert int(argv[argv.index('--source-max')+1]) == entry['start'] + entry['count']
        assert argv[argv.index('--source-mnemonic')+1] == entry['mnemonic'] == MNEMONIC
        assert entry['wd_address'] == servers[name].getWithdrawAddress()

    old_cwd = Path.cwd()
    try:
        output = tmp_path / 'output'
        compiler = ChainSeedDocker(internetMapEnabled=False)
        emu.compile(compiler, str(output))
    finally:
        os.chdir(old_cwd)
    compose = yaml.safe_load((output / 'docker-compose.yml').read_text())
    inventory = json.loads(content(system.getHost('lookingglass'), '/opt/chainseed/lookingglass/inventory.json'))
    beacons = {node['label']: node for node in inventory['nodes'] if node['role'] == 'beacon'}
    assert beacons['b0']['metrics_port'] == 5055
    assert beacons['b1']['metrics_port'] is None
    for service in compose['services'].values():
        environment = service.get('environment', [])
        assert 'GOMEMLIMIT' not in str(environment)  # scoped to the client process
    for path in output.rglob('*'):
        if not path.is_file():
            continue
        text = path.read_text()
        if text.startswith('#!/bin/bash'):
            subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)
    assert any('--cache 128' in path.read_text() for path in output.rglob('*') if path.is_file())


def test_defaults_preserve_standard_examples(network):
    emu, system, _, _ = network
    emu.render()
    assert '--cache' not in starts(system.getHost('g0'))
    assert 'GOMEMLIMIT' not in starts(system.getHost('g0'))
    beacon = content(system.getHost('b0'), '/tmp/beacon-bootstrapper')
    assert '--beacon-processor-max-workers' not in beacon
    assert '--metrics' not in beacon
    assert '--reconstruct-historic-states' in beacon
    assert 'GENESIS_TIME=`date +%s`' in starts(system.getHost('setup'))
    entries = yaml.safe_load(content(system.getHost('setup'), '/tmp/mnemonic.yaml'))
    assert [(e['start'], e['count']) for e in entries] == [(0, 1), (1, 1), (2, 1)]


def test_configuration_freezes_after_render(network):
    emu, _, _, servers = network
    emu.render()
    actions = [lambda: servers['g0'].setCacheMiB(256),
               lambda: servers['g0'].setGoMemoryLimitMiB(512),
               lambda: servers['g0'].setRpcTxFeeCap(0),
               lambda: servers['b0'].setProcessorMaxWorkers(4),
               lambda: servers['b0'].enableMetrics(),
               lambda: servers['b0'].connectToGethNode('g1'),
               lambda: servers['v0'].setValidatorKeyCount(10),
               lambda: servers['setup'].setValidatorMnemonic(MNEMONIC),
               lambda: servers['setup'].setGenesisDelay(0),
               lambda: servers['v0'].setBootstrapRetryPolicy(attempts=3)]
    for action in actions:
        with pytest.raises(RuntimeError, match='before emu.render'):
            action()


def test_invalid_values_are_rejected(network):
    _, _, _, servers = network
    actions = [lambda: servers['g0'].setCacheMiB(-1),
               lambda: servers['g0'].setGoMemoryLimitMiB(True),
               lambda: servers['g0'].setRpcTxFeeCap(float('nan')),
               lambda: servers['g0'].setRpcTxFeeCap(-1),
               lambda: servers['b0'].setProcessorMaxWorkers(0),
               lambda: servers['b0'].setReconstructHistoricStates('false'),
               lambda: servers['b0'].enableMetrics(port=65536),
               lambda: servers['b0'].enableMetrics(address='bad host'),
               lambda: servers['v0'].setValidatorKeyCount(1.5),
               lambda: servers['setup'].setGenesisDelay(-1),
               lambda: servers['setup'].setValidatorMnemonic(''),
               lambda: servers['v0'].setBootstrapRetryPolicy(attempts=0),
               lambda: servers['v0'].setBootstrapRetryPolicy(connect_timeout_seconds=0)]
    for action in actions:
        with pytest.raises(ValueError):
            action()


def test_custom_geth_flag_conflicts_are_rejected(network):
    emu, _, _, servers = network
    servers['g0'].setCacheMiB(128).setCustomGethCommandOption('--cache=512')
    with pytest.raises(ValueError, match='also configured'):
        emu.render()


def test_metrics_port_collision_is_reported_before_compilation(network):
    emu, _, _, servers = network
    servers['b0'].enableMetrics(port=8000)
    with pytest.raises(ValueError, match='metrics port 8000 conflicts'):
        emu.render()


def test_runtime_validator_cannot_silently_ignore_multiplexing(network):
    emu, system, chain, _ = network
    system.createHost('runtime').joinNetwork('net0')
    chain.createVcNode('runtime').enablePOSValidatorAtRunning().setValidatorKeyCount(2)
    emu.addBinding(Binding('runtime', action=Action.FIRST, filter=Filter(asn=150, nodeName='^runtime$')))
    with pytest.raises(ValueError, match='requires enablePOSValidatorAtGenesis'):
        emu.render()


def test_lookingglass_respects_metrics_port_and_disabled_endpoint(monkeypatch):
    from chainseed.services.ethereum.LookingglassServer import app as server

    requests = []
    monkeypatch.setattr(server, 'fetch', lambda url, **kwargs: requests.append(url) or '')
    node = dict(id='beacon', ip='10.150.0.71', role='beacon', metrics_port=5055)
    probe = server.PeerProbe([node])
    probe.metrics(node)
    assert requests == ['http://10.150.0.71:5055/metrics']
    node['metrics_port'] = None
    probe.metrics(node)
    assert len(requests) == 1


def test_bootstrap_download_stops_after_configured_attempts(network, tmp_path):
    emu, system, _, servers = network
    servers['b0'].setBootstrapRetryPolicy(attempts=2, interval_seconds=0)
    emu.render()
    script = content(system.getHost('b0'), '/tmp/beacon-bootstrapper')
    nodes = tmp_path / 'setup-endpoints'
    nodes.write_text('10.150.0.79:8090\n')
    script = script.replace('/tmp/beacon-setup-node', str(nodes))
    curl = tmp_path / 'curl'
    requests = tmp_path / 'requests'
    curl.write_text('#!/bin/sh\nprintf "request\\n" >> "$REQUEST_LOG"\nexit 22\n')
    curl.chmod(0o755)
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
        env=dict(os.environ, PATH=f'{tmp_path}:' + os.environ['PATH'], REQUEST_LOG=str(requests)), timeout=5)
    assert result.returncode == 1
    assert requests.read_text().splitlines() == ['request', 'request']
    assert 'failed too many times' in result.stdout
    assert 'starting lighthouse' not in result.stdout


def test_explorer_explicit_targets_reach_compose_and_selected_network(network, tmp_path):
    emu, system, chain, servers = network
    # Put the observer pair on a different AS and give it a non-default RPC port.
    base = emu.getLayer('Base')
    observer_as = base.createAutonomousSystem(151)
    observer_net = observer_as.createNetwork('net0')
    observer_as.createRouter('router0').joinNetwork('net0')
    for name in ('observer-geth', 'observer-beacon'):
        observer_as.createHost(name).joinNetwork('net0')
        emu.addBinding(Binding(name, action=Action.FIRST, filter=Filter(asn=151, nodeName=f'^{name}$')))
    observer_geth = chain.createGethNode('observer-geth').enableGethHttp().setGethHttpPort(9545)
    observer_beacon = chain.createBeaconNode('observer-beacon').connectToGethNode('observer-geth')
    observer_beacon.setReconstructHistoricStates(True)
    servers['g0'].enableGethHttp()
    # Identical display names must not influence the virtual-node selectors.
    observer_geth.setDisplayName('same-name')
    servers['g0'].setDisplayName('same-name')
    servers['b0'].setReconstructHistoricStates(False)
    emu.render()
    compiler = ChainSeedDocker(internetMapEnabled=False).enableEthExplorer(
        'pos', geth_vnode='observer-geth', beacon_vnode='observer-beacon')
    old_cwd = Path.cwd()
    try:
        output = tmp_path / 'output'
        emu.compile(compiler, str(output))
    finally:
        os.chdir(old_cwd)
    compose = yaml.safe_load((output / 'docker-compose.yml').read_text())
    geth_ip = str(observer_as.getHost('observer-geth').getInterfaces()[0].getAddress())
    beacon_ip = str(observer_as.getHost('observer-beacon').getInterfaces()[0].getAddress())
    selected_net = compiler._getRealNetName(observer_net)
    original_net = compiler._getRealNetName(system.getNetwork('net0'))
    for name in ('seedemu-ethexplorer-backend', 'seedemu-ethexplorer-web'):
        spec = compose['services'][name]
        environment = dict(value.split('=', 1) for value in spec['environment'])
        assert environment == dict(EL_HOST=geth_ip, EL_PORT='9545', CL_HOST=beacon_ip, CL_PORT='8000')
        assert selected_net in spec['networks']
        assert original_net not in spec['networks']
    subprocess.run(['docker', 'compose', '-p', 'chainseed-explorer-selection-test',
                    '-f', str(output / 'docker-compose.yml'), 'config', '--quiet'],
                   check=True, capture_output=True)


def test_explorer_auto_and_partial_selection_use_eligible_servers(network):
    from chainseed.services.ethereum import EthExplorer

    emu, system, _, servers = network
    servers['g1'].enableGethHttp().setGethHttpPort(9546)
    servers['b0'].setReconstructHistoricStates(False)
    emu.render()
    for selectors in ({}, {'geth_vnode': 'g1'}, {'beacon_vnode': 'b1'}):
        component = EthExplorer('pos', **selectors)
        services = component.getComposeServices(emu, lambda net: net.getName())
        env = services['seedemu-ethexplorer-backend']['environment']
        geth_ip = system.getHost('g1').getInterfaces()[0].getAddress()
        beacon_ip = system.getHost('b1').getInterfaces()[0].getAddress()
        assert f'EL_HOST={geth_ip}' in env and 'EL_PORT=9546' in env
        assert f'CL_HOST={beacon_ip}' in env


def test_explorer_invalid_targets_fail_without_falling_back(network):
    from chainseed.services.ethereum import EthExplorer

    emu, system, _, servers = network
    servers['g1'].enableGethHttp()
    servers['b0'].setReconstructHistoricStates(False)
    system.createHost('foreign').joinNetwork('net0')
    emu.addBinding(Binding('foreign', action=Action.FIRST, filter=Filter(asn=150, nodeName='^foreign$')))
    foreign_chain = emu.getLayer('EthereumService').createBlockchain('other', ConsensusMechanism.POS)
    foreign_chain.createGethNode('foreign').enableGethHttp()
    emu.render()
    cases = [({'geth_vnode': 'missing'}, 'does not exist'),
             ({'beacon_vnode': 'missing'}, 'does not exist'),
             ({'geth_vnode': 'b1'}, 'must be a PoS Geth'),
             ({'beacon_vnode': 'g1'}, 'must be a PoS Beacon'),
             ({'geth_vnode': 'foreign'}, 'not in chain'),
             ({'geth_vnode': 'g0'}, 'requires enableGethHttp'),
             ({'beacon_vnode': 'b0'}, 'requires setReconstructHistoricStates')]
    for selectors, message in cases:
        with pytest.raises(ValueError, match=message):
            EthExplorer('pos', **selectors).getComposeServices(emu, lambda net: net.getName())


@pytest.mark.parametrize('role', ['Geth', 'Beacon'])
def test_explorer_reports_no_eligible_automatic_target(network, role):
    from chainseed.services.ethereum import EthExplorer

    emu, _, _, servers = network
    if role == 'Beacon':
        servers['g1'].enableGethHttp()
        servers['b0'].setReconstructHistoricStates(False)
        servers['b1'].setReconstructHistoricStates(False)
    emu.render()
    with pytest.raises(ValueError, match=f'needs a {role} server'):
        EthExplorer('pos').getComposeServices(emu, lambda net: net.getName())


def test_explorer_selector_arguments_validate_before_render():
    from chainseed.services.ethereum import EthExplorer

    for selectors in ({'geth_vnode': ''}, {'geth_vnode': 1},
                      {'beacon_vnode': ' '}, {'beacon_vnode': False}):
        with pytest.raises(ValueError, match='virtual node name'):
            EthExplorer('pos', **selectors)
        with pytest.raises(ValueError, match='virtual node name'):
            ChainSeedDocker().enableEthExplorer('pos', **selectors)
