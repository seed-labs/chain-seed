"""Exercise the global viewer through binding, compilation and runtime inputs."""

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
import yaml

from seedemu.compiler import Docker
from seedemu.core import Action, Binding, Emulator, Filter, Server
from seedemu.layers import Base, Routing
from chainseed.ethereum import ConsensusMechanism, EthereumService, EthereumServer, LookingglassServer
from chainseed.ethereum.LookingglassServer.app import PeerProbe, State
from chainseed.ethereum.LookingglassServer.sources import RunSource


ROOT = LookingglassServer.DIR_PREFIX


def network():
    emu, base, eth = Emulator(), Base(), EthereumService()
    for asn in (150, 151):
        system = base.createAutonomousSystem(asn)
        system.createNetwork('net0')
        system.createRouter('router0').joinNetwork('net0')
    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(eth)

    def bind(name, asn=150):
        host = base.getAutonomousSystem(asn).createHost(name).joinNetwork('net0')
        emu.addBinding(Binding(name, action=Action.FIRST,
                               filter=Filter(asn=asn, nodeName=f'^{name}$')))
        return host

    viewer = eth.createLookingglassServer()
    host = bind('lookingglass')
    return emu, eth, viewer, host, bind


def inventory(host):
    return json.loads(host.getFile(ROOT + '/inventory.json').get()[1])


def test_global_inventory_has_all_chains_without_client_side_effects():
    emu, eth, viewer, host, bind = network()
    pos = eth.createBlockchain('pos', ConsensusMechanism.POS)
    geth = pos.createGethNode('g').enableGethHttp().setStaticPeers([])
    beacon = pos.createBeaconNode('b').setBootNode(True).connectToGethNode('g')
    beacon.setProcessorMaxWorkers(3).enableMetrics(port=5055)
    pos.createVcNode('v').enablePOSValidatorAtGenesis().setValidatorKeyCount(2).connectToBeaconNode('b')
    pos.createBeaconSetupNode('setup')
    for name in ('g', 'b', 'v', 'setup'):
        bind(name)
    legacy = eth.createBlockchain('legacy', ConsensusMechanism.POA)
    disabled = legacy.createGethNode('old')
    bind('old', 151)
    emu.render()
    doc = inventory(host)
    nodes = {node['id']: node for node in doc['nodes']}
    assert doc['chains'] == ['pos', 'legacy']
    assert set(nodes) == {'g', 'b', 'v', 'old'}
    assert nodes['old']['chain'] == 'legacy' and nodes['old']['asn'] == '151'
    assert nodes['old']['rpc_port'] is None and not disabled.isGethHttpEnabled()
    assert nodes['g']['enode'] == geth.getP2PEnode()
    assert nodes['b']['metrics_port'] == 5055 and nodes['b']['cap'] == 3
    assert nodes['v']['keys'] == 2
    assert {(edge['source'], edge['target']) for edge in doc['edges']} == {('b', 'g'), ('v', 'b')}
    assert all(edge['kind'] == 'service' for edge in doc['edges'])
    assert isinstance(viewer, Server) and not isinstance(viewer, EthereumServer)
    assert all('lookingglass' not in chain._pending_targets for chain in (pos, legacy))
    commands = '\n'.join(command for command, _ in host.getStartCommands())
    assert '--host 0.0.0.0 --port 8765' in commands
    assert '--probe-peers' in commands and '--peer-interval 10' in commands
    assert host.getPorts() == [(8765, 8765, 'tcp')]
    with pytest.raises(RuntimeError, match='before emu.render'):
        viewer.setPort(9999)


def test_singleton_and_optional_configuration():
    emu, eth, viewer, host, _ = network()
    assert eth.createLookingglassServer() is viewer
    with pytest.raises(ValueError, match='only one'):
        eth.createLookingglassServer('second')
    assert not hasattr(viewer, 'setTargets') and not hasattr(viewer, 'setHostPort')
    viewer.setPort(9001).setProbePolicy(enabled=False, peer_interval=20, metrics_interval=30, workers=2)
    for change in (lambda: viewer.setPort(True), lambda: viewer.setPort(65536),
                   lambda: viewer.setProbePolicy(peer_interval=float('nan')),
                   lambda: viewer.setProbePolicy(workers=0),
                   lambda: viewer.setProbePolicy(enabled=1)):
        with pytest.raises(ValueError):
            change()
    assert viewer.getPort() == 9001
    emu.render()
    command = next(command for command, _ in host.getStartCommands() if '-m lookingglass.app' in command)
    assert '--probe-peers' not in command and '--peer-interval 20' in command
    assert '--metrics-interval 30' in command and '--peer-jobs 2' in command
    assert host.getPorts() == [(9001, 9001, 'tcp')]


def test_existing_vnode_cannot_be_replaced():
    eth = EthereumService()
    eth.createBlockchain('poa', ConsensusMechanism.POA).createGethNode('lookingglass')
    with pytest.raises(ValueError, match='already belongs'):
        eth.createLookingglassServer()


def test_host_port_conflicts_are_reported():
    emu, _, _, _, bind = network()
    bind('web', 151).addPort(8765, 80)
    with pytest.raises(ValueError, match='host port 8765'):
        emu.render()


def test_native_docker_compiles_host_publication_runtime_and_readonly_mount(tmp_path):
    emu, _, viewer, host, _ = network()
    observations = tmp_path / 'observations'
    viewer.setObservationDirectory(observations)
    emu.render()
    cwd = Path.cwd()
    output = tmp_path / 'output'
    try:
        emu.compile(Docker(internetMapEnabled=False), str(output))
    finally:
        os.chdir(cwd)
    compose = yaml.safe_load((output / 'docker-compose.yml').read_text())
    service = next(spec for spec in compose['services'].values()
                   if spec.get('ports') == ['8765:8765/tcp'])
    assert len(service['networks']) == 1
    assert any(volume.get('source') == str(observations) and volume.get('read_only')
               for volume in service.get('volumes', []) if isinstance(volume, dict))
    assert 'chainseed-lookingglass' not in compose['services']
    context = output / service['build']
    assert 'python3-yaml' in (context / 'Dockerfile').read_text()
    copies = {parts[2]: context / parts[1] for line in (context / 'Dockerfile').read_text().splitlines()
              if len(parts := line.split()) == 3 and parts[0] == 'COPY'}
    assert json.loads(copies[ROOT + '/inventory.json'].read_text()) == inventory(host)
    assert all(ROOT + '/' + name in copies for name in ('__init__.py', 'app.py', 'sources.py', 'static/app.js', 'static/index.html'))
    subprocess.run(['bash', '-n', str(copies['/start.sh'])], check=True, capture_output=True)
    subprocess.run(['docker', 'compose', '-p', 'lookingglass-test', '-f', str(output / 'docker-compose.yml'),
                    'config', '--quiet'], check=True, capture_output=True)
    # E12 preserves this node's build while converting client services to mounts.
    from tools.blockchain.lib.runtime_mounts import patch_output
    patch_output(output, output / 'docker-compose.yml', '/seedemu-node', 524288, False, False)
    assert (context / 'Dockerfile').read_text().startswith('FROM handsonsecurity/')
    subprocess.run(['docker', 'compose', '-p', 'lookingglass-test', '-f', str(output / 'docker-compose.yml'),
                    'config', '--quiet'], check=True, capture_output=True)


def test_inventory_configuration_survives_optional_collector_files(tmp_path):
    path = tmp_path / 'inventory.json'
    path.write_text(json.dumps(dict(title='Ethereum global view', chains=['one', 'two'], edges=[], nodes=[
        dict(id='v', role='validator', ip='10.150.0.71', asn='150', host='h', keys=2),
        dict(id='b', role='beacon', ip='10.150.0.72', asn='150', host='bn', cap=3),
    ])))
    source = RunSource(inventory=path)
    source.snapshot()
    # Collectors may start after the viewer; association uses explicit host labels.
    (tmp_path / 'observed-compose.yml').write_text(yaml.safe_dump({'services': {
        'legacy': {'container_name': 'old-container', 'labels': {
            'org.seedsecuritylabs.seedemu.meta.asn': '150',
            'org.seedsecuritylabs.seedemu.meta.nodename': 'h'}}}}))
    (tmp_path / 'deployment.json').write_text(json.dumps(dict(keys_per_client=999, worker_cap=999)))
    (tmp_path / 'memory_latest_raw.csv').write_text('container_name,mem_usage_bytes,cpu_percent,sample,timestamp\n'
                                                  'old-container,1073741824,1,1,2026-10-20T00:00:00Z\n')
    state = State(source)
    state.update()
    data = json.loads(state.payload)
    nodes = {node['id']: node for node in data['nodes']}
    assert data['run'] == 'Ethereum global view' and data['chains'] == ['one', 'two']
    assert nodes['v']['keys'] == 2 and nodes['b']['cap'] == 3
    assert nodes['v']['memory_gib'] == 1


def test_empty_inventory_can_start_and_disabled_rpc_is_not_queried(tmp_path):
    path = tmp_path / 'inventory.json'
    path.write_text(json.dumps(dict(title='Ethereum global view', nodes=[], edges=[])))
    state = State(RunSource(inventory=path), probes=True)
    state.update()
    assert json.loads(state.payload)['nodes'] == []
    assert PeerProbe([dict(id='g', role='geth', ip='10.150.0.71', rpc_port=None)]).nodes == []


def test_runtime_resources_work_after_relocation_and_from_zip(tmp_path):
    emu, _, _, host, _ = network()
    emu.render()
    package = tmp_path / 'relocated_viewer'
    names = ('__init__.py', 'app.py', 'sources.py', 'static/__init__.py',
             'static/index.html', 'static/app.js', 'static/style.css')
    for name in names:
        destination = package / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(host.getFile(ROOT + '/' + name).get()[1])
    archive = tmp_path / 'viewer.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name in names:
            bundle.write(package / name, 'relocated_viewer/' + name)
    script = (
        'import sys; from relocated_viewer import app; '
        'assert b"<!doctype html>" in app.read_static("index.html"); '
        'assert not any(n == "seedemu" or n.startswith("seedemu.") '
        'or n == "chainseed" or n.startswith("chainseed.") for n in sys.modules); '
        'sys.argv = ["relocated_viewer.app", "--help"]; app.main()'
    )
    elsewhere = tmp_path / 'unrelated-working-directory'
    elsewhere.mkdir()
    for import_path in (tmp_path, archive):
        result = subprocess.run([sys.executable, '-c', script], cwd=elsewhere,
                                env=dict(os.environ, PYTHONPATH=str(import_path)),
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert '--inventory' in result.stdout


def test_static_assets_support_older_runtime_python(monkeypatch):
    from chainseed.ethereum.LookingglassServer import app
    monkeypatch.delattr(app.resources, 'files')
    assert b'<!doctype html>' in app.read_static('index.html')


def test_peer_matching_is_scoped_to_chain():
    nodes = [dict(id=name, role='geth', ip='10.150.0.71', chain=name)
             for name in ('one', 'two')]
    probe = PeerProbe(nodes)
    probe.identities = {'one': 'a', 'two': 'b'}
    probe.samples = {'one': dict(ids=['b'], addresses={'b': '10.150.0.71'}, error=None, at=1)}
    data = dict(nodes=nodes, edges=[], capabilities={})
    probe.merge(data)
    assert data['edges'] == []
