"""Bind one immutable native campaign, then run one owner-host wave."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import tarfile
from pathlib import Path

from Mallory.native_graphchecker_campaign.campaign import _validate_config
from Mallory.native_graphchecker_dispatch.checklist import (
    _native_case_files, _verify_alternate_junit, inspect_case,
    load_ownership,
)
from .inventory_epoch import load_queue_inventory
from .queue import (atomic, obj, physical_host, pilot_receipt, run_host,
                    sha, validate_isolation)

DEFAULT_ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/Mallory/native-102-queue-v2')


def binding_for(item: dict, config_path: Path, state_path: Path,
                *, alternate: Path | None = None,
                alternate_source_receipt: Path | None = None,
                identity: Path | None = None,
                adapter_proof: Path | None = None,
                recording_admission: Path | None = None,
                validation_stdout: Path | None = None,
                target_source_archive: Path | None = None,
                campaign_python_root: Path | None = None,
                campaign_python_tar: Path | None = None) -> dict:
    if (not config_path.is_absolute() or not state_path.is_absolute() or
            config_path.is_symlink() or state_path.is_symlink() or
            not config_path.is_file()):
        raise ValueError('native config/state must be absolute non-symlink paths')
    config = obj(config_path)
    _validate_config(config)
    case_id = item['case_id']
    native_id = config.get('case_id')
    if (not isinstance(native_id, str) or
            not (native_id == case_id or native_id.startswith(case_id + '-native-')) or
            config.get('runner', {}).get('mode') not in ('region_state', 'concolic') or
            config.get('target_throw', {}).get('siteId') != item['target']['site_id'] or
            config.get('target_throw', {}).get('exceptionClass') != item[
                'target'].get('target_exception') or
            config.get('target_site', '').split('#', 1)[0] != item[
                'target']['site_id'].split('#', 1)[0]):
        raise ValueError('native config does not match exact inventory target')
    expected = {'class': item['workload']['test_class'],
                'method': item['workload']['test_method']}
    if config.get('junit') != expected and alternate is None:
        raise ValueError('alternate original JUnit requires pinned attestation')
    if alternate is not None and (not alternate.is_absolute() or
                                  alternate.is_symlink() or
                                  not alternate.is_file()):
        raise ValueError('alternate JUnit attestation is not immutable')
    if alternate_source_receipt is not None and (
            alternate is None or not alternate_source_receipt.is_absolute() or
            alternate_source_receipt.is_symlink() or
            not alternate_source_receipt.is_file()):
        raise ValueError('shared alternate source requires a pinned attestation')
    row_sha = hashlib.sha256(json.dumps(
        item, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    runner_mode = config['runner']['mode']
    binding = {'schema_version': 1,
               'mode': ('native_region_state_case_binding' if runner_mode ==
                        'region_state' else 'native_concolic_case_binding'),
               'inventory_case_id': case_id,
               'inventory_row_sha256': row_sha,
               'native_case_id': native_id,
               'native_config_path': str(config_path),
               'native_config_sha256': sha(config_path),
               'native_state_path': str(state_path)}
    direct = {'adapter_proof': adapter_proof,
              'recording_admission': recording_admission,
              'validation_stdout': validation_stdout}
    if runner_mode == 'concolic':
        if any(direct[name] is None for name in (
                'adapter_proof', 'recording_admission', 'validation_stdout')):
            raise ValueError('direct concolic admission requires all three receipts')
        direct['zero_vm_java'] = Path(config['runner'].get('zero_vm_java', ''))
        for name, path in direct.items():
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                raise ValueError(f'direct concolic {name} is not immutable')
        binding['direct_admission'] = {
            name: {'path': str(path), 'sha256': sha(path)}
            for name, path in direct.items()}
        if target_source_archive is not None:
            if (not target_source_archive.is_absolute() or
                    target_source_archive.is_symlink() or
                    not target_source_archive.is_file() or
                    sha(target_source_archive) != item['target']['source_sha256']):
                raise ValueError('direct concolic target source archive changed')
            binding['target_source_archive'] = {
                'path': str(target_source_archive),
                'sha256': sha(target_source_archive)}
    elif any(path is not None for path in direct.values()):
        raise ValueError('direct concolic admission requires concolic runner')
    elif target_source_archive is not None:
        raise ValueError('source archive is only for direct concolic admission')
    if alternate is not None:
        binding['alternate_original_junit'] = {
            'attestation_path': str(alternate), 'attestation_sha256': sha(alternate)}
        if alternate_source_receipt is not None:
            binding['alternate_original_junit'].update({
                'shared_source_receipt_path': str(alternate_source_receipt),
                'shared_source_receipt_sha256': sha(alternate_source_receipt)})
    if identity is not None:
        if not identity.is_absolute() or identity.is_symlink() or not identity.is_file():
            raise ValueError('native target identity audit is not immutable')
        binding['target_identity_audit'] = {'path': str(identity),
                                            'sha256': sha(identity)}
    if (campaign_python_root is None) != (campaign_python_tar is None):
        raise ValueError('campaign Python root and source tar must be paired')
    if runner_mode == 'concolic' and campaign_python_root is None:
        raise ValueError('direct concolic campaign requires frozen source closure')
    if campaign_python_root is not None:
        from .queue import pinned_campaign_python
        source = {'root_path': str(campaign_python_root),
                  'source_tar_path': str(campaign_python_tar),
                  'source_tar_sha256': sha(campaign_python_tar),
                  'python_sha256': {
                      str(path.relative_to(campaign_python_root)): sha(path)
                      for path in sorted(campaign_python_root.rglob('*.py'))}}
        if runner_mode == 'concolic':
            relative = 'Mallory/native_graphchecker_feedback/NativeFeedbackMain.java'
            java = campaign_python_root / relative
            if java.is_symlink() or not java.is_file():
                raise ValueError('concolic campaign source lacks NativeFeedbackMain.java')
            with tarfile.open(campaign_python_tar, 'r:*') as archive:
                try:
                    member = archive.getmember(relative)
                except KeyError as failure:
                    raise ValueError('concolic campaign tar lacks NativeFeedbackMain.java') from failure
                stream = archive.extractfile(member) if member.isfile() else None
                if stream is None or hashlib.sha256(stream.read()).hexdigest() != sha(java):
                    raise ValueError('concolic campaign Java source differs from tar')
            source['required_files_sha256'] = {relative: sha(java)}
        pinned_campaign_python(source)
        binding['campaign_python_source'] = source
    return binding


def extend_profile(profile: dict, system: str, case_id: str,
                   review: Path | None,
                   config_sha256: str | None = None) -> dict:
    """Add a pinned case port review, including reviewed assigned-port changes."""
    copied = json.loads(json.dumps(profile))
    ports = copied['systems'][system]['ports']
    if ports['mode'] == 'assigned':
        if review is None:
            return copied
        if (not review.is_absolute() or review.is_symlink() or
                not review.is_file() or config_sha256 is None):
            raise ValueError('assigned port change requires a pinned case review')
        receipt = obj(review)
        address = receipt.get('port_range', {})
        thread_id = address.get('thread_id')
        start = address.get('start')
        count = address.get('count')
        end = address.get('end')
        expected_arg = f'-Dzookeeper.junit.threadid={thread_id}'
        if (receipt.get('schema_version') != 1 or
                receipt.get('kind') != 'native_assigned_port_case_review' or
                receipt.get('system') != system or
                receipt.get('case_id') != case_id or
                receipt.get('native_config_sha256') != config_sha256 or
                any(not isinstance(value, int) or isinstance(value, bool)
                    for value in (thread_id, start, count, end)) or
                thread_id < 1 or start < 1024 or count < 1 or
                end != start + count - 1 or end > 65535 or
                receipt.get('required_jvm_args') != [expected_arg]):
            raise ValueError('assigned port review differs from case config')
        source = receipt.get('source_evidence', {})
        ready = receipt.get('ready', {})
        admission = receipt.get('admission', {})
        for name, entry in (("source", source), ("ready", ready),
                            ("admission", admission)):
            path = Path(entry.get('path', ''))
            if (not path.is_absolute() or path.is_symlink() or
                    not path.is_file() or sha(path) != entry.get('sha256')):
                raise ValueError(f'assigned port {name} evidence changed')
        if ports.get('evidence', {}).get(source['path']) != source['sha256']:
            raise ValueError('assigned port source is not in isolation profile')
        ready_doc = obj(Path(ready['path']))
        admission_doc = obj(Path(admission['path']))
        if (ready_doc.get('case_id') != case_id or
                ready_doc.get('case_config_sha256') != config_sha256 or
                ready_doc.get('thread_id') != thread_id or
                ready_doc.get('port_range') != [start, end] or
                admission_doc.get('port_range') != {
                    'start': start, 'end': end, 'thread_id': thread_id} or
                admission_doc.get('paths_sha256', {}).get('config') !=
                    config_sha256 or
                admission_doc['paths_sha256'].get('ready') != ready['sha256']):
            raise ValueError('assigned port admission differs from review')
        if case_id not in ports.get('cases', {}):
            raise ValueError('assigned port case is absent from isolation profile')
        ports['cases'][case_id] = {
            'start': start, 'count': count,
            'required_jvm_args': [expected_arg]}
        ports['evidence'][str(review)] = sha(review)
        ports['evidence'][ready['path']] = ready['sha256']
        ports['evidence'][admission['path']] = admission['sha256']
        return copied
    if review is None or not review.is_absolute() or review.is_symlink() or not review.is_file():
        raise ValueError('dynamic ports require an absolute case source review')
    receipt = obj(review)
    if receipt.get('schema_version') != 1 or receipt.get('system') != system or (
            receipt.get('case_id') != case_id):
        raise ValueError('port source review is for a different case')
    source = (receipt.get('reviewed_source_sha256') if ports['mode'] ==
              'random_retry' else receipt.get('evidence'))
    if not isinstance(source, dict) or not source:
        raise ValueError('port source review has no source digests')
    for name, digest in source.items():
        path = Path(name)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
                sha(path) != digest):
            raise ValueError(f'port source evidence changed: {name}')
    cases = ports.setdefault('case_receipts', {})
    previous = ports.pop('receipt', None)
    if previous is not None:
        old = obj(Path(previous))
        cases.setdefault(old['case_id'], previous)
    if case_id in cases and cases[case_id] != str(review):
        raise ValueError('case port review is already pinned elsewhere')
    cases[case_id] = str(review)
    ports['evidence'][str(review)] = sha(review)
    ports['evidence'].update(source)
    return copied


def swap_unbound_reservation(original: dict, extended: dict, *,
                             case_id: str, displaced_case_id: str,
                             host: str, ownership: dict[str, str],
                             config_root: Path, state_root: Path,
                             profile_sha256: str,
                             ownership_sha256: str,
                             review_path: Path | None) -> tuple[dict, dict]:
    """Move only an unused assigned reservation when a direct case owns it."""
    if (not isinstance(displaced_case_id, str) or
            displaced_case_id == case_id or
            ownership.get(case_id) != host or
            ownership.get(displaced_case_id) != host or
            review_path is None or not review_path.is_absolute() or
            review_path.is_symlink() or not review_path.is_file() or
            (config_root / f'{displaced_case_id}.json').exists() or
            (state_root / displaced_case_id).exists()):
        raise ValueError('assigned reservation swap requires an unbound same-host case')
    review = obj(review_path)
    if (review.get('schema_version') != 1 or
            review.get('kind') != 'unbound_assigned_port_reservation_review' or
            review.get('case_id') != case_id or
            review.get('displaced_case_id') != displaced_case_id or
            review.get('host') != host or
            review.get('isolation_sha256') != profile_sha256 or
            review.get('ownership_sha256') != ownership_sha256 or
            review.get('displaced_binding_absent') is not True or
            review.get('prepared_case_root_absent') is not True or
            review.get('active_process_absent') is not True or
            review.get('checked_hosts') != ['node0', 'node1', 'node2']):
        raise ValueError('unbound assigned-port review differs from queue state')
    observations = review.get('evidence', {})
    for checked_host in ('node0', 'node1', 'node2'):
        entry = observations.get(checked_host, {})
        path = Path(entry.get('path', ''))
        if (not path.is_absolute() or path.is_symlink() or
                not path.is_file() or sha(path) != entry.get('sha256') or
                obj(path) != entry.get('observations')):
            raise ValueError('unbound assigned-port host observation changed')
        host_observation = entry['observations']
        if (not host_observation.get('hostname', '').startswith(checked_host + '.') or
                any(host_observation.get(key) != [] for key in (
                    'matching_prepared_roots', 'matching_processes',
                    'matching_tmux_sessions'))):
            raise ValueError('displaced case has a prepared root or active process')
    old_ports = original['systems']['zookeeper']['ports']
    new_ports = extended['systems']['zookeeper']['ports']
    if old_ports.get('mode') != 'assigned' or new_ports.get('mode') != 'assigned':
        raise ValueError('reservation swap requires assigned ZooKeeper ports')
    old_target = old_ports['cases'].get(case_id)
    old_displaced = old_ports['cases'].get(displaced_case_id)
    new_target = new_ports['cases'].get(case_id)
    if (not isinstance(old_target, dict) or
            not isinstance(old_displaced, dict) or
            new_target != old_displaced or old_target == old_displaced):
        raise ValueError('direct port review does not match unused reservation')
    new_ports['cases'][displaced_case_id] = old_target
    migration = {'schema_version': 1,
                 'kind': 'unbound_assigned_port_reservation_swap',
                 'case_id': case_id, 'displaced_case_id': displaced_case_id,
                 'host': host, 'previous_case_assignment': old_target,
                 'previous_displaced_assignment': old_displaced,
                 'new_case_assignment': new_target,
                 'new_displaced_assignment': old_target,
                 'previous_isolation_sha256': profile_sha256,
                 'unbound_review_path': str(review_path),
                 'unbound_review_sha256': sha(review_path)}
    return extended, migration


def promote(*, root: Path, case_id: str, native_config: Path,
            native_state: Path, host: str,
            shared_state_root: Path | None = None,
            pilot_receipt_path: Path | None = None,
            port_review: Path | None = None,
            reservation_swap_with: str | None = None,
            unbound_reservation_review: Path | None = None,
            alternate_attestation: Path | None = None,
            alternate_source_receipt: Path | None = None,
            target_identity_audit: Path | None = None,
            adapter_proof: Path | None = None,
            recording_admission: Path | None = None,
            validation_stdout: Path | None = None,
            target_source_archive: Path | None = None,
            campaign_python_root: Path | None = None,
            campaign_python_tar: Path | None = None,
            epoch_receipt: Path | None = None,
            epoch_receipt_sha256: str | None = None,
            dispatch: bool = True) -> dict:
    physical_host(host)
    if root.name.startswith('native-102-queue-v15') and epoch_receipt is None:
        raise ValueError('v15 promotion requires the explicit inventory epoch')
    if case_id == 'HDFS-40' and epoch_receipt is None:
        raise ValueError('HDFS-40 promotion requires the explicit v15 inventory epoch')
    if (epoch_receipt is not None and
            not root.name.startswith('native-102-queue-v15')):
        raise ValueError('v15 promotion requires an isolated v15 queue root')
    inventory = root / 'python-snapshot-bind-v4/Mallory/cases/inventory.json'
    ownership = root / 'config/ownership.json'
    config_root = root / 'config'
    state_root = shared_state_root or root / 'state'
    profile_path = root / 'evidence/isolation.json'
    pilot = pilot_receipt_path or (state_root /
                                   '.native-queue/pilot-ZOOKEEPER-07.json')
    if epoch_receipt is not None:
        if (shared_state_root is None or pilot_receipt_path is None or
                not pilot.is_relative_to(root) or
                not state_root.is_absolute()):
            raise ValueError('v15 promotion requires a separate pilot and '
                             'explicit shared state root')
    cases, by_id, epoch = load_queue_inventory(
        inventory, state_root, epoch_receipt, epoch_receipt_sha256)
    item = next((row for row in cases if row['case_id'] == case_id), None)
    if item is None:
        raise ValueError('case is absent from canonical 102-row inventory')
    owners = load_ownership(ownership, set(by_id))
    queue_root = state_root / '.native-queue'
    queue_root.mkdir(parents=True, exist_ok=True)
    with (queue_root / 'promotion.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for owner_host in ('node0', 'node1', 'node2'):
            controller = queue_root / 'controllers' / f'{owner_host}.json'
            if controller.is_file() and obj(controller).get('status') == 'running':
                raise ValueError('queue controller is running during promotion')
        # Verify the last pilot pin before changing ownership or isolation.
        pilot_receipt(pilot, inventory, ownership, config_root, state_root,
                      cases, owners, profile_path)
        new_owners = dict(owners)
        new_owners[case_id] = host
        ownership_doc = obj(ownership)
        ownership_doc['owner'] = new_owners
        ownership_doc['counts'] = {name: sum(value == name for value in
                                            new_owners.values()) for name in
                                   ('node0', 'node1', 'node2')}
        ownership_doc['basis'] = 'physical owner of immutable native campaign'
        original_profile = obj(profile_path)
        profile = extend_profile(original_profile, item['system'], case_id,
                                 port_review, sha(native_config))
        migration = None
        if reservation_swap_with is not None:
            if item['system'] != 'zookeeper' or port_review is None:
                raise ValueError('reservation swap requires assigned ZooKeeper review')
            profile, migration = swap_unbound_reservation(
                original_profile, profile, case_id=case_id,
                displaced_case_id=reservation_swap_with, host=host,
                ownership=new_owners, config_root=config_root,
                state_root=state_root, profile_sha256=sha(profile_path),
                ownership_sha256=sha(ownership),
                review_path=unbound_reservation_review)
        elif unbound_reservation_review is not None:
            raise ValueError('unbound reservation review needs a swap case')
        binding = binding_for(item, native_config, native_state,
                              alternate=alternate_attestation,
                              alternate_source_receipt=alternate_source_receipt,
                              identity=target_identity_audit,
                              adapter_proof=adapter_proof,
                              recording_admission=recording_admission,
                              validation_stdout=validation_stdout,
                              target_source_archive=target_source_archive,
                              campaign_python_root=campaign_python_root,
                              campaign_python_tar=campaign_python_tar)
        for other_path in config_root.glob('*.json'):
            if other_path.stem in ('ownership', case_id):
                continue
            other = obj(other_path)
            if other.get('mode') in ('native_region_state_case_binding',
                                     'native_concolic_case_binding'):
                other_state = Path(other['native_state_path'])
                if (native_state == other_state or
                        native_state.is_relative_to(other_state) or
                        other_state.is_relative_to(native_state)):
                    raise ValueError('native state root overlaps another case')
        config = obj(native_config)
        validate_isolation(profile, item['system'], case_id, config,
                           new_owners, host)
        candidate_dir = queue_root / 'promotion-candidate' / case_id
        candidate_binding = candidate_dir / f'{case_id}.json'
        atomic(candidate_binding, binding)
        if alternate_attestation is not None:
            # The dispatcher verifies the source, compiled test, Resolver, and
            # official healthy result before accepting an alternate selector.
            _verify_alternate_junit(item, candidate_binding, config)
        checkpoint = native_state / 'checkpoint.json'
        if checkpoint.is_file():
            state = obj(checkpoint)
            if (state.get('case_id') != config['case_id'] or
                    state.get('config_sha256') != sha(native_config)):
                raise ValueError('existing native checkpoint has another config')
        inspected = inspect_case(item, host, candidate_dir, state_root)
        if inspected['terminal_disposition'] not in (
                'ready', 'resumable', 'tested_candidate',
                'tested_no_target_throw', 'tested_inconclusive'):
            raise ValueError(f'native case is not dispatchable: {inspected}')
        binding_path = config_root / f'{case_id}.json'
        if binding_path.is_file() and obj(binding_path) != binding:
            previous = obj(binding_path)
            prior_shape = json.loads(json.dumps(binding))
            prior_alternate = prior_shape.get('alternate_original_junit', {})
            prior_alternate.pop('shared_source_receipt_path', None)
            prior_alternate.pop('shared_source_receipt_sha256', None)
            if (alternate_source_receipt is None or previous != prior_shape):
                raise ValueError('native binding already pins different inputs')
        # No queue worker is active. Refresh the pilot's ownership/isolation
        # digest along with the two launch documents under this promotion lock.
        atomic(ownership, ownership_doc)
        atomic(profile_path, profile)
        atomic(binding_path, binding)
        pilot_doc = obj(pilot)
        pilot_doc['ownership_sha256'] = sha(ownership)
        pilot_doc['isolation_sha256'] = sha(profile_path)
        atomic(pilot, pilot_doc)
        resolved, resolved_root = _native_case_files(item, config_root, state_root)
        if resolved != native_config or resolved_root != native_state:
            raise ValueError('promoted native binding resolved differently')
        pilot_receipt(pilot, inventory, ownership, config_root, state_root,
                      cases, new_owners, profile_path)
        receipt = {'schema_version': 1, 'case_id': case_id, 'host': host,
                   'binding_path': str(binding_path),
                   'binding_sha256': sha(binding_path),
                   'config_sha256': sha(native_config),
                   'checkpoint_status': inspected.get('status'),
                   'terminal_disposition': inspected['terminal_disposition'],
                   'ownership_sha256': sha(ownership),
                   'isolation_sha256': sha(profile_path)}
        if migration is not None:
            migration['new_isolation_sha256'] = sha(profile_path)
            migration['binding_sha256'] = sha(binding_path)
            migration_path = (queue_root / 'promotions' /
                              f'{case_id}-port-reservation-swap.json')
            atomic(migration_path, migration)
            receipt['port_reservation_swap_path'] = str(migration_path)
            receipt['port_reservation_swap_sha256'] = sha(migration_path)
        if epoch is not None:
            receipt['inventory_epoch'] = epoch
        atomic(queue_root / 'promotions' / f'{case_id}.json', receipt)
    if dispatch:
        receipt['worker_exit_codes'] = run_host(
            host=host, slots=2, pilot=pilot, inventory=inventory,
            ownership_file=ownership, config_root=config_root,
            state_root=state_root, scratch_root=root / 'scratch',
            isolation_file=profile_path,
            results_dir=(root / 'results-v15' if epoch is not None else
                         root / 'results'),
            epoch_receipt=epoch_receipt,
            epoch_receipt_sha256=epoch_receipt_sha256)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--host', choices=('node0','node1','node2'), required=True)
    parser.add_argument('--native-config', type=Path, required=True)
    parser.add_argument('--native-state', type=Path, required=True)
    parser.add_argument('--shared-state-root', type=Path)
    parser.add_argument('--pilot-receipt-path', type=Path)
    parser.add_argument('--port-review', type=Path)
    parser.add_argument('--reservation-swap-with')
    parser.add_argument('--unbound-reservation-review', type=Path)
    parser.add_argument('--alternate-attestation', type=Path)
    parser.add_argument('--alternate-source-receipt', type=Path)
    parser.add_argument('--target-identity-audit', type=Path)
    parser.add_argument('--adapter-proof', type=Path)
    parser.add_argument('--recording-admission', type=Path)
    parser.add_argument('--validation-stdout', type=Path)
    parser.add_argument('--target-source-archive', type=Path)
    parser.add_argument('--campaign-python-root', type=Path)
    parser.add_argument('--campaign-python-tar', type=Path)
    parser.add_argument('--inventory-epoch-receipt', type=Path)
    parser.add_argument('--inventory-epoch-sha256')
    parser.add_argument('--bind-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(promote(
        root=args.root, case_id=args.case_id, host=args.host,
        native_config=args.native_config, native_state=args.native_state,
        shared_state_root=args.shared_state_root,
        pilot_receipt_path=args.pilot_receipt_path,
        port_review=args.port_review,
        reservation_swap_with=args.reservation_swap_with,
        unbound_reservation_review=args.unbound_reservation_review,
        alternate_attestation=args.alternate_attestation,
        alternate_source_receipt=args.alternate_source_receipt,
        target_identity_audit=args.target_identity_audit,
        adapter_proof=args.adapter_proof,
        recording_admission=args.recording_admission,
        validation_stdout=args.validation_stdout,
        target_source_archive=args.target_source_archive,
        campaign_python_root=args.campaign_python_root,
        campaign_python_tar=args.campaign_python_tar,
        epoch_receipt=args.inventory_epoch_receipt,
        epoch_receipt_sha256=args.inventory_epoch_sha256,
        dispatch=not args.bind_only), sort_keys=True))


if __name__ == '__main__':
    main()
