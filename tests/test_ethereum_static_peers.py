"""Validate planned Geth links through Node files and compiled client commands."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from eth_keys import keys
import pytest
import tomli
import yaml

from chainseed import ChainSeedDocker
from chainseed.services.ethereum import ConsensusMechanism, EthereumService
from seedemu.core import Action, Binding, Emulator, Filter
from seedemu.layers import Base, Routing


KEY_PATH = '/tmp/geth-p2p-nodekey'
CONFIG_PATH = '/tmp/geth-peers.toml'


def make_network(consensus=ConsensusMechanism.POA):
    emu = Emulator()
    base = Base()
    systems = {}
    for asn in (150, 151):
        system = base.createAutonomousSystem(asn)
        system.createNetwork('net0')
        system.createRouter('router0').joinNetwork('net0')
        systems[asn] = system
    eth = EthereumService()
    chain = eth.createBlockchain('peers', consensus)
    servers, hosts = {}, {}
    for name, asn in [('g0', 150), ('g2', 150), ('g1', 151)]:
        hosts[name] = systems[asn].createHost(name).joinNetwork('net0')
        emu.addBinding(Binding(name, action=Action.FIRST, filter=Filter(asn=asn, nodeName=f'^{name}$')))
        servers[name] = chain.createGethNode(name)
    if consensus != ConsensusMechanism.POS:
        servers['g0'].startMiner()
    servers['g0'].setBootNode(True)
    emu.addLayer(base)
    emu.addLayer(Routing())
    emu.addLayer(eth)
    return emu, chain, servers, hosts


@pytest.fixture
def network():
    return make_network()


def file_text(host, path):
    return host.getFile(path).get()[1]


def start_commands(host):
    return [command for command, _ in host.getStartCommands()]


@pytest.mark.parametrize('consensus', [ConsensusMechanism.POA, ConsensusMechanism.POS, ConsensusMechanism.POW])
def test_static_path_uses_actual_client_keys_and_ports(consensus, tmp_path):
    emu, chain, servers, hosts = make_network(consensus)
    for server in servers.values():
        server.setNoDiscover(True).setMaxPeers(8)
    servers['g0'].setStaticPeers(['g1']).addStaticPeer('g1')
    servers['g1'].setStaticPeers(['g2'])
    servers['g2'].setStaticPeers([])
    emu.render()
    for name, target in [('g0', 'g1'), ('g1', 'g2'), ('g2', None)]:
        server, host = servers[name], hosts[name]
        key = bytes.fromhex(file_text(host, KEY_PATH).strip())
        public = keys.PrivateKey(key).public_key.to_bytes().hex()
        address = host.getInterfaces()[0].getAddress()
        assert server.getP2PEnode() == f'enode://{public}@{address}:30303'
        config = tomli.loads(file_text(host, CONFIG_PATH))
        expected = [servers[target].getP2PEnode()] if target else []
        assert config == {'Node': {'P2P': {'StaticNodes': expected}}}
        commands = start_commands(host)
        # PoW must also register a launch command, not only generate its string.
        launch = next(c for c in commands if c.startswith(('geth --datadir', 'nice -n 19 geth')))
        argv = shlex.split(launch)
        assert argv[argv.index('--nodekey')+1] == KEY_PATH
        assert argv[argv.index('--config')+1] == CONFIG_PATH
        assert argv[argv.index('--maxpeers')+1] == '8'
        assert '--nodiscover' in argv and '--bootnodes' not in argv
        assert '/tmp/eth-bootstrapper' not in '\n'.join(commands)
        assert f'chmod 600 {KEY_PATH}' in commands

    old_cwd = Path.cwd()
    try:
        output = tmp_path / 'output'
        emu.compile(ChainSeedDocker(internetMapEnabled=False), str(output))
    finally:
        os.chdir(old_cwd)
    compose = yaml.safe_load((output / 'docker-compose.yml').read_text())
    for spec in compose['services'].values():
        context = spec.get('build')
        if not isinstance(context, str):
            continue
        directory = output / context
        copies = {parts[2]: directory / parts[1] for line in (directory/'Dockerfile').read_text().splitlines()
                  if len(parts := line.split()) == 3 and parts[0] == 'COPY'}
        if CONFIG_PATH not in copies:
            continue
        assert tomli.loads(copies[CONFIG_PATH].read_text())['Node']['P2P']['StaticNodes'] is not None
        subprocess.run(['bash', '-n', str(copies['/start.sh'])], check=True, capture_output=True)
    subprocess.run(['docker', 'compose', '-p', 'chainseed-static-peers-test',
                    '-f', str(output/'docker-compose.yml'), 'config', '--quiet'], check=True, capture_output=True)


def test_unconfigured_targets_gain_identity_without_a_reverse_dial(network):
    emu, _, servers, hosts = network
    servers['g0'].setStaticPeers(['g1']).setNoDiscover(True)
    emu.render()
    expected = servers['g1'].getP2PEnode()
    assert expected.endswith(':30303') and ':30301' not in expected
    assert file_text(hosts['g1'], KEY_PATH)
    assert servers['g1'].getStaticPeers() == []
    assert '--config' not in '\n'.join(start_commands(hosts['g1']))
    config = tomli.loads(file_text(hosts['g0'], CONFIG_PATH))
    assert config['Node']['P2P']['StaticNodes'] == [expected]
    assert servers['g2'].getP2PEnode() is None


def test_unconfigured_clients_keep_original_startup(network):
    emu, _, servers, hosts = network
    emu.render()
    for name, server in servers.items():
        commands = '\n'.join(start_commands(hosts[name]))
        assert KEY_PATH not in commands and CONFIG_PATH not in commands
        assert '--maxpeers' not in commands
        assert '/tmp/eth-bootstrapper' in commands
        assert server.getP2PEnode() is None


def test_identity_and_declarations_survive_unrendered_dump(network, tmp_path):
    emu, _, servers, _ = network
    servers['g0'].setStaticPeers(['g1']).setNoDiscover(True)
    declarations = servers['g0'].getStaticPeers()
    declarations.append('g2')
    assert servers['g0'].getStaticPeers() == ['g1']
    original_keys = {name: server._p2p_private_key for name, server in servers.items()}
    dump = tmp_path / 'network.bin'
    emu.dump(str(dump))
    restored = Emulator().load(str(dump))
    restored.render()
    targets = restored.getLayer('EthereumService').getPendingTargets()
    for name, key in original_keys.items():
        assert targets[name]._p2p_private_key == key
    expected = targets['g1'].getP2PEnode()
    for server, host in restored.getLayer('EthereumService').getTargets():
        if server is targets['g0']:
            assert tomli.loads(file_text(host, CONFIG_PATH))['Node']['P2P']['StaticNodes'] == [expected]
    for change in (lambda: targets['g0'].setStaticPeers([]),
                   lambda: targets['g0'].addStaticPeer('g2'),
                   lambda: targets['g0'].setMaxPeers(3)):
        with pytest.raises(RuntimeError, match='before emu.render'):
            change()


@pytest.mark.parametrize('peer, message', [('g0', 'itself'), ('missing', 'does not exist'),
                                          ('beacon', 'Geth execution server'), ('foreign', 'same blockchain')])
def test_bad_peer_references_fail_during_render(network, peer, message):
    emu, chain, servers, hosts = network
    system = emu.getLayer('Base').getAutonomousSystem(150)
    eth = emu.getLayer('EthereumService')
    for name in ('beacon', 'foreign'):
        system.createHost(name).joinNetwork('net0')
        emu.addBinding(Binding(name, action=Action.FIRST, filter=Filter(asn=150, nodeName=f'^{name}$')))
    eth.createBlockchain('consensus', ConsensusMechanism.POS).createBeaconNode('beacon')
    eth.createBlockchain('other', ConsensusMechanism.POA).createGethNode('foreign')
    servers['g0'].setStaticPeers([peer])
    with pytest.raises(ValueError, match=message):
        emu.render()


def test_peer_inputs_are_validated_atomically(network):
    _, _, servers, _ = network
    server = servers['g0'].setStaticPeers(['g1', 'g1'])
    assert server.getStaticPeers() == ['g1']
    for value in ('g2', None, ['g2', 2], [''], [False]):
        with pytest.raises(ValueError):
            server.setStaticPeers(value)
        assert server.getStaticPeers() == ['g1']
    for value in ('', None, 1):
        with pytest.raises(ValueError):
            server.addStaticPeer(value)
    for value in (-1, True, 1.5):
        with pytest.raises(ValueError):
            server.setMaxPeers(value)
    assert servers['g1'].getStaticPeers() == []


@pytest.mark.parametrize('option', ['--config other.toml', '--nodekey other.key',
                                   '--nodekeyhex 1234', '--port=40404', '--maxpeers 12'])
def test_conflicting_custom_options_are_rejected(network, option):
    emu, _, servers, _ = network
    servers['g0'].setStaticPeers(['g1']).setNoDiscover(True).setMaxPeers(8)
    servers['g0'].setCustomGethCommandOption(option)
    with pytest.raises(ValueError, match='conflicts.*P2P'):
        emu.render()


def test_zero_maxpeers_cannot_silently_disable_declared_links(network):
    emu, _, servers, _ = network
    servers['g0'].setStaticPeers(['g1']).setMaxPeers(0)
    with pytest.raises(ValueError, match='disables networking'):
        emu.render()


def test_forward_references_resolve_after_hosts_are_bound(network):
    emu, chain, servers, _ = network
    servers['g0'].setStaticPeers(['late']).setNoDiscover(True)
    late = chain.createGethNode('late')
    system = emu.getLayer('Base').getAutonomousSystem(151)
    system.createHost('late-host').joinNetwork('net0')
    emu.addBinding(Binding('late', action=Action.FIRST, filter=Filter(asn=151, nodeName='^late-host$')))
    emu.render()
    source = emu.getBindingFor('g0')
    config = tomli.loads(file_text(source, CONFIG_PATH))
    late_ip = emu.getBindingFor('late').getInterfaces()[0].getAddress()
    assert late.getP2PEnode().endswith(f'@{late_ip}:30303')
    assert config['Node']['P2P']['StaticNodes'] == [late.getP2PEnode()]
