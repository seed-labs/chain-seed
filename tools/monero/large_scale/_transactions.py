#!/usr/bin/env python3
"""Private-testnet wallet transfers, durable submission journal and two-node receipts."""
import hashlib
import json
import math
import os
from pathlib import Path
import time

import requests
from requests.auth import HTTPDigestAuth

ATOMIC = 10**12


class RpcError(RuntimeError):
    pass


class Endpoint:
    def __init__(self, url, user=None, password=None):
        self.url = url
        self.session = requests.Session()
        self.session.trust_env = False
        if user:
            self.session.auth = HTTPDigestAuth(user, password)

    def call(self, method, params=None, plain=False):
        body = params or {}
        url = self.url
        if plain:
            url = url.rsplit('/', 1)[0] + '/' + method
        else:
            body = dict(jsonrpc='2.0', id='m01', method=method, params=body)
        response = self.session.post(url, json=body, timeout=(5, 60))
        response.raise_for_status()
        data = response.json()
        if data.get('error'):
            raise RpcError(str(data['error']))
        result = data if plain else data['result']
        if result.get('status', 'OK') != 'OK':
            raise RpcError(str(result))
        return result


def confirmed_on_both(txid, observations):
    rows = [view.get(txid) for view in observations]
    return len(rows) == 2 and all(r and r.get('in_pool') is False
        and not r.get('double_spend_seen', False) and r.get('block_height', 0) > 0
        for r in rows) and rows[0]['block_height'] == rows[1]['block_height']


class Load:
    def __init__(self, deployment, directory, rate, funding_rounds=16, clock=time.monotonic,
                 guard=lambda: None, funding=False):
        self.deployment = Path(deployment)
        self.directory = Path(directory)
        self.rate, self.funding_rounds, self.clock, self.guard = rate, funding_rounds, clock, guard
        self.records = json.loads((self.deployment/'wallets.json').read_text())
        if sum(r['role'] == 'funder' for r in self.records) != 1 or sum(r['role'] == 'sender' for r in self.records) < 2:
            raise ValueError('Deployment requires one funding wallet and at least two senders')
        self.wallets = [Endpoint(r['url'], r['user'], r['password']) for r in self.records]
        self.funder = next(i for i, r in enumerate(self.records) if r['role'] == 'funder')
        self.senders = [i for i, r in enumerate(self.records) if r['role'] == 'sender']
        nodes = json.loads((self.deployment/'nodes.json').read_text())
        # An ingress and a remote full node: an RPC acknowledgement is not inclusion.
        observers = [nodes[0], nodes[-1]]
        self.daemons = [Endpoint(f"http://{n['ip']}:{n['rpc_port']}/json_rpc") for n in observers]
        self.raw = self.directory/('funding' if funding else 'transactions')
        self.raw.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.journal = (self.raw/'events.jsonl').open('x', buffering=1)
        self.known = {}
        self.sent = self.attempted = self.skipped = self.prepare_failed = 0
        self.query_errors = 0
        self.start = None
        self.end = None
        self.ring_size = None
        self.addresses = []
        self.event('configuration', rate=rate, funding_rounds=funding_rounds,
                   sender_indices=[self.records[i]['index'] for i in self.senders],
                   observers=observers, amount_atomic=ATOMIC//100,
                   note='Existing private testnet; not a modern-mainnet workload model')

    def event(self, kind, durable=False, **fields):
        self.journal.write(json.dumps(dict(time=time.time(), event=kind, **fields))+'\n')
        if durable:
            self.journal.flush()
            os.fsync(self.journal.fileno())

    def pause(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end:
            self.guard()
            time.sleep(min(2, end - self.clock()))

    def submit(self, wallet, address, amount, phase):
        params = dict(destinations=[dict(address=address, amount=amount)],
                      account_index=0, priority=1, do_not_relay=True, get_tx_metadata=True)
        if self.ring_size is not None:
            params['ring_size'] = self.ring_size
        # Only construction errors are recoverable; never create a replacement after
        # an uncertain relay. Persist the hash/metadata before the first broadcast.
        try:
            result = self.wallets[wallet].call('transfer', params)
        except RpcError as error:
            self.event('prepare_rejected', phase=phase, wallet=wallet, error=str(error))
            return None
        txid, metadata = result['tx_hash'], result['tx_metadata']
        if not txid or not metadata or txid in self.known:
            raise RuntimeError('Invalid or duplicate prepared transaction')
        self.known[txid] = dict(phase=phase, wallet=wallet, prepared_at=time.time(),
                                accepted=False, confirmed=False)
        self.event('prepared', durable=True, phase=phase, wallet=wallet, txid=txid,
                   metadata=metadata, amount_atomic=amount, fee_atomic=result.get('fee'))
        for attempt in range(3):
            try:
                response = self.wallets[wallet].call('relay_tx', dict(hex=metadata))
                if response['tx_hash'] != txid:
                    raise RuntimeError('Relay hash mismatch')
                self.known[txid]['accepted'] = True
                self.event('accepted', phase=phase, txid=txid, attempt=attempt, durable=True)
                return txid
            except (requests.RequestException, RpcError) as error:
                self.event('relay_error', txid=txid, attempt=attempt, error=str(error))
                self.pause(2)
        raise RuntimeError(f'Unresolved relay for {txid}; no replacement transaction was generated')

    def observe(self, final=False):
        hashes = [h for h, r in self.known.items() if final or not r['confirmed']]
        views = []
        for observer, daemon in enumerate(self.daemons):
            view = {}
            for offset in range(0, len(hashes), 100):
                self.guard()
                batch = hashes[offset:offset+100]
                try:
                    result = daemon.call('get_transactions', dict(txs_hashes=batch,
                        decode_as_json=False, prune=True), plain=True)
                    rows = {r['tx_hash']: {k: r.get(k) for k in
                            ('tx_hash', 'in_pool', 'block_height', 'double_spend_seen')}
                            for r in result.get('txs', [])}
                    view.update(rows)
                    self.event('receipts', observer=observer, requested=batch, rows=rows,
                               missed=result.get('missed_tx', []), final=final)
                except (requests.RequestException, RpcError, ValueError) as error:
                    self.query_errors += 1
                    self.event('receipt_error', observer=observer, error=str(error), final=final)
            views.append(view)
        for txid in hashes:
            confirmed = confirmed_on_both(txid, views)
            if confirmed and not self.known[txid]['confirmed']:
                self.event('first_inclusion', txid=txid,
                    latency_sec=time.time()-self.known[txid]['prepared_at'],
                    block_height=views[0][txid]['block_height'])
            self.known[txid]['confirmed'] = confirmed

    def prepare(self, timeout=10800):
        deadline = self.clock() + timeout

        def wait_for(predicate, label):
            while self.clock() < deadline:
                self.guard()
                try:
                    if predicate():
                        return
                except (requests.RequestException, RpcError) as error:
                    self.event('warmup_query_error', stage=label, error=str(error))
                self.event('warmup_wait', stage=label)
                self.pause(15)
            raise RuntimeError(f'Monero wallet warmup timed out: {label}')

        def ready():
            self.addresses = [w.call('get_address', dict(account_index=0))['address']
                              for w in self.wallets]
            return len(set(self.addresses)) == len(self.wallets)

        wait_for(ready, 'wallet RPC')
        info = self.daemons[0].call('get_info')
        if not info.get('testnet'):
            raise RuntimeError('Refuse to send workload outside the private testnet')
        fork = self.daemons[0].call('hard_fork_info')
        # v1 permits no decoys; later forks keep the wallet's protocol defaults.
        # This is deliberately not represented as a modern RingCT benchmark.
        self.ring_size = 1 if fork['version'] == 1 else None
        self.event('protocol', info=info, hard_fork=fork, ring_size=self.ring_size)
        for round_index in range(self.funding_rounds):
            for wallet in self.senders:
                def funded():
                    self.wallets[self.funder].call('refresh')
                    balance = self.wallets[self.funder].call('get_balance')
                    self.event('funding_balance', balance=balance)
                    if balance['unlocked_balance'] < 11*ATOMIC:
                        return False
                    return self.submit(self.funder, self.addresses[wallet], 10*ATOMIC, 'funding') is not None
                wait_for(funded, f'funding wallet {wallet} round {round_index}')

        def unlocked():
            ready_wallets = []
            for wallet in self.senders:
                self.wallets[wallet].call('refresh')
                result = self.wallets[wallet].call('incoming_transfers', dict(transfer_type='available', account_index=0))
                usable = [r for r in result.get('transfers', []) if r.get('unlocked') is True
                          and not r.get('spent') and r['amount'] >= ATOMIC]
                ready_wallets.append(len(usable) >= self.funding_rounds)
                self.event('funding_outputs', wallet=wallet, usable=len(usable), response=result)
            return all(ready_wallets)

        wait_for(unlocked, 'funded outputs unlocked')
        self.observe(final=True)
        if not all(r['confirmed'] for r in self.known.values()):
            raise RuntimeError('Funding inclusion not verified on both observer nodes')
        self.event('warmup_complete', durable=True)

    def save_ready(self):
        payload = dict(addresses=self.addresses, ring_size=self.ring_size,
            funding_rounds=self.funding_rounds, ready_at=time.time(),
            inputs={name: hashlib.sha256((self.deployment/name).read_bytes()).hexdigest()
                    for name in ('nodes.json', 'wallets.json')})
        with (self.directory/'wallets-ready.json').open('x') as handle:
            json.dump(payload, handle, indent=2)

    def load_ready(self):
        payload = json.loads((self.directory/'wallets-ready.json').read_text())
        for name, digest in payload['inputs'].items():
            if hashlib.sha256((self.deployment/name).read_bytes()).hexdigest() != digest:
                raise ValueError('Wallet preparation belongs to a different deployment')
        self.addresses = [w.call('get_address', dict(account_index=0))['address'] for w in self.wallets]
        if self.addresses != payload['addresses']:
            raise ValueError('Wallet addresses changed; prepare wallets again in a new run directory')
        if not self.daemons[0].call('get_info').get('testnet'):
            raise RuntimeError('Refuse to send workload outside the private testnet')
        self.ring_size = 1 if self.daemons[0].call('hard_fork_info')['version'] == 1 else None
        self.funding_rounds = payload['funding_rounds']
        self.event('prepared_wallets_loaded', funding_rounds=self.funding_rounds,
                   ring_size=self.ring_size)

    def begin(self, duration):
        self.start = self.clock()
        self.end = self.start + duration
        self.next_send = self.start
        self.next_poll = self.start
        self.duration = duration
        self.event('sampling_start', duration=duration, rate=self.rate, durable=True)
        (self.raw/'sampling.json').write_text(json.dumps(dict(start=time.time(), duration=duration,
                                                            rate=self.rate)))

    def tick(self):
        now = self.clock()
        if now >= self.end:
            return
        if now >= self.next_poll:
            self.observe()
            self.next_poll = self.clock() + 60
        now = self.clock()
        if now >= self.end:
            return
        if now >= self.next_send:
            # No catch-up burst: missed offered load is explicit, never concealed.
            missed = int((now-self.next_send)*self.rate)
            self.skipped += missed
            self.next_send += (missed+1)/self.rate
            wallet_pos = self.attempted % len(self.senders)
            wallet = self.senders[wallet_pos]
            recipient = self.senders[(wallet_pos+1) % len(self.senders)]
            self.attempted += 1
            txid = self.submit(wallet, self.addresses[recipient], ATOMIC//100, 'load')
            if txid:
                self.sent += 1
            else:
                self.prepare_failed += 1
            self.event('load_progress', attempted=self.attempted, sent=self.sent,
                       skipped=self.skipped, prepare_failed=self.prepare_failed)

    def finish(self, drain_timeout=1200):
        self.event('sampling_end', durable=True)
        deadline = self.clock() + drain_timeout
        while True:
            self.observe(final=True)
            if all(r['confirmed'] for r in self.known.values()) or self.clock() >= deadline:
                break
            self.pause(min(15, max(0, deadline-self.clock())))
        return summarize(self.directory)

    def close(self):
        self.journal.close()


def summarize(directory):
    raw = Path(directory)/'transactions'
    sampling = json.loads((raw/'sampling.json').read_text())
    known, final_views, progress = {}, {}, {}
    ended = False
    with (raw/'events.jsonl').open() as handle:
        for line in handle:
            row = json.loads(line)
            event = row['event']
            if event == 'prepared' and row['phase'] == 'load':
                known[row['txid']] = dict(accepted=False)
            elif event == 'accepted' and row['txid'] in known:
                known[row['txid']]['accepted'] = True
            elif event == 'load_progress':
                progress = row
            elif event == 'sampling_end':
                ended = True
            elif event == 'receipts' and row.get('final'):
                view = final_views.setdefault(row['observer'], {})
                for txid in row['requested']:
                    view.pop(txid, None)
                view.update(row['rows'])
            elif event == 'receipt_error' and row.get('final'):
                # A final failed query cannot reuse stale successful evidence.
                final_views[row['observer']] = {}
    accepted = sum(r['accepted'] for r in known.values())
    included = sum(confirmed_on_both(h, [final_views.get(0, {}), final_views.get(1, {})]) for h in known)
    expected = math.ceil(sampling['duration']*sampling['rate'])
    achievement = 100*accepted/expected if expected else 0
    counters_match = (bool(progress) and progress.get('sent') == accepted
        and progress.get('attempted') == len(known)+progress.get('prepare_failed', 0))
    result = dict(target_tps=sampling['rate'], expected=expected, prepared=len(known),
                  accepted=accepted, included_both_observers=included,
                  unresolved_at_end=len(known)-included,
                  attempted=progress.get('attempted', 0), skipped=progress.get('skipped', 0),
                  prepare_failed=progress.get('prepare_failed', 0),
                  send_achievement_pct=achievement, sampling_completed=ended,
                  counters_match=counters_match)
    result['status'] = 'passed' if (ended and expected > 0 and achievement >= 95
        and counters_match and accepted == included == len(known)
        and not result['prepare_failed']) else 'failed'
    (raw/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
