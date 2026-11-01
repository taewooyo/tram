"""Operational contracts exercised in isolated projects and owned sessions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

RUNTIME = Path(__file__).resolve().parents[1] / 'src/runtime/tram.py'
spec = importlib.util.spec_from_file_location('operational_tram', RUNTIME)
tram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tram)


@pytest.fixture
def project(tmp_path):
    tram.init(tmp_path)
    (tmp_path / 'code.py').write_text('value = 1\n')
    configure(tmp_path, [sys.executable, '-c', 'print("ok")'])
    tram.start(tmp_path, 'sample', 'quick')
    tram.transition(tmp_path, 'sample', 'verify')
    return tmp_path


def configure(root, argv=None, **changes):
    value = {'commands': [{'id': 'test', 'argv': argv or [sys.executable, '-c', 'pass'],
                          'cwd': '.', 'confirmed': True, 'required': True, 'timeout': 3}],
             'inputs': ['code.py'], **changes}
    file = root / '.tram/local/config.json'
    file.write_text(json.dumps(value))
    return tram.configure(root, file)


def cli(root, *args, timeout=15):
    return subprocess.run([sys.executable, str(RUNTIME), *args, '--project', str(root)],
                          capture_output=True, text=True, timeout=timeout, start_new_session=True)


def tree(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode)
            for p in root.rglob('*') if p.is_file()}


def error(code, function, *args, **kwargs):
    with pytest.raises(tram.TramError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_schema_defaults_contract_and_legacy_write_guard(project):
    config = tram.profile(project)
    assert config['schema_version'] == 2
    assert config['diagnostics'] == tram.DIAGNOSTICS
    assert config['metrics']['enabled'] is True
    assert config['retain_raw_output'] is False
    assert tram.contract()['verify_run']['exit']['cancelled'] == 130
    for relative in tram.state_paths(project):
        value = json.loads((project / relative).read_text())
        value['schema_version'] = 1
        (project / relative).write_text(json.dumps(value))
    before = tree(project)
    assert tram.status(project, 'sample')['task']['schema_version'] == 1
    assert tram.doctor(project)['writes'] is False
    assert tram.migration_preview(project)['writes'] is False
    assert tree(project) == before
    error('SCHEMA_MIGRATION_REQUIRED', tram.start, project, 'other', 'quick')


def test_explicit_roundtrip_preserves_inputs_approvals_and_blocks_old_completion(project):
    tram.verify_run(project, 'sample', 'test')
    tram.transition(project, 'sample', 'complete')
    old_inputs = tram.profile(project)['inputs']
    preview = tram.migrate(project, 'preview', 2, 1)
    before = tree(project)
    assert tree(project) == before
    report = tram.migrate(project, 'apply', 2, 1, preview['digest'])
    value = json.loads((project / '.tram/tasks/sample.json').read_text())
    assert value['phase'] == 'verifying'
    assert value['verification'][-1]['stale'] is True
    assert 'diagnostics' not in json.loads((project / '.tram/project.json').read_text())
    old_runtime = Path(__file__).resolve().parents[1] / '.tram/local/operational-readiness-baseline/source/src/runtime/tram.py'
    if old_runtime.exists():
        run = subprocess.run([sys.executable, str(old_runtime), 'status', '--project', str(project), '--slug', 'sample'], capture_output=True, text=True)
        assert run.returncode == 0
        assert json.loads(run.stdout)['result']['effective_phase'] != 'complete'
    preview = tram.migrate(project, 'preview', 1, 2)
    tram.migrate(project, 'apply', 1, 2, preview['digest'])
    assert tram.profile(project)['inputs'] == old_inputs
    assert tram.status(project, 'sample')['effective_phase'] != 'complete'
    assert report['backup']


def test_migration_digest_conflict_and_backup_checksum(project):
    preview = tram.migrate(project, 'preview', 2, 1)
    path = project / '.tram/project.json'
    value = json.loads(path.read_text())
    value['revision'] += 1
    path.write_text(json.dumps(value))
    error('DIGEST_CONFLICT', tram.migrate, project, 'apply', 2, 1, preview['digest'])
    preview = tram.migrate(project, 'preview', 2, 1)
    report = tram.migrate(project, 'apply', 2, 1, preview['digest'])
    manifest = tram.backup_manifest(project, report['backup'])
    entry = next(iter(manifest['entries'].values()))
    (project / '.tram/local' / entry['original']).write_text('corrupt')
    error('BACKUP_CHECKSUM_MISMATCH', tram.restore, project, 'preview', report['backup'])


def test_old_runtime_rejects_schema2(project):
    old = RUNTIME.parents[2] / '.tram/local/operational-readiness-baseline/source/src/runtime/tram.py'
    if not old.exists():
        pytest.skip('preserved 0.1.0 baseline unavailable')
    result = subprocess.run([sys.executable, str(old), 'status', '--project', str(project)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)['errorCode'] == 'SCHEMA_INCOMPATIBLE'


def test_doctor_accumulates_damage_without_writes(project):
    (project / '.tram/project.json').write_text('{')
    (project / '.tram/tasks/sample.json').write_text('null')
    before = tree(project)
    result = tram.doctor(project)
    assert len([e for e in result['files'] if not e['readable']]) == 2
    assert tree(project) == before


def test_recover_dead_lock_live_unknown_and_preview_conflict(project):
    path = project / '.tram/local/write.lock'
    owner = {'pid': os.getpid(), 'start_id': tram.process_identity(os.getpid()), 'token': 'live'}
    path.write_text(json.dumps(owner))
    report = tram.recover(project)
    assert report['liveness'] == 'live'
    error('LOCK_OWNER_UNSAFE', tram.recover, project, 'apply', report['digest'], 'live')
    path.write_text(json.dumps({'pid': os.getpid(), 'token': 'unknown'}))
    report = tram.recover(project)
    assert report['liveness'] == 'unknown'
    error('LOCK_OWNER_UNSAFE', tram.recover, project, 'apply', report['digest'], 'unknown')
    dead = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    dead.wait()
    path.write_text(json.dumps({'pid': dead.pid, 'start_id': 'dead-fixture', 'token': 'dead'}))
    report = tram.recover(project)
    assert report['liveness'] == 'dead'
    path.write_text(path.read_text() + '\n')
    error('DIGEST_CONFLICT', tram.recover, project, 'apply', report['digest'], 'dead')
    report = tram.recover(project)
    task_before = (project / '.tram/tasks/sample.json').read_bytes()
    result = tram.recover(project, 'apply', report['digest'], 'dead')
    assert not path.exists()
    assert (project / '.tram/tasks/sample.json').read_bytes() == task_before
    assert result['backup']


def test_restore_refuses_newer_changes_and_never_revives_complete(project):
    tram.verify_run(project, 'sample', 'test')
    tram.transition(project, 'sample', 'complete')
    preview = tram.migrate(project, 'preview', 2, 1)
    report = tram.migrate(project, 'apply', 2, 1, preview['digest'])
    restore_preview = tram.restore(project, 'preview', report['backup'])
    tram.restore(project, 'apply', report['backup'], restore_preview['digest'])
    assert tram.status(project, 'sample')['effective_phase'] != 'complete'
    error('RESTORE_CONFLICT', tram.restore, project, 'preview', report['backup'])


@pytest.mark.parametrize('exit_code,expected', [(0, 0), (7, 1)])
def test_cli_separates_recording_from_execution(project, exit_code, expected):
    configure(project, [sys.executable, '-c', 'raise SystemExit(' + str(exit_code) + ')'])
    run = cli(project, 'verify-run', '--slug', 'sample', '--command', 'test')
    result = json.loads(run.stdout)
    assert run.returncode == expected
    assert result['recorded'] is True
    assert result['ok'] is (exit_code == 0)
    assert result['result']['exit_code'] == exit_code
    assert result['errorCode'] == (None if exit_code == 0 else 'VERIFY_FAILED')
    assert cli(project, 'verify-run', '--slug', 'sample', '--command', 'unknown').returncode == 2


def test_child_eof_cannot_execute_command(project):
    process = subprocess.Popen([sys.executable, str(RUNTIME), '_child', 'no-permit'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    stdout, stderr = process.communicate(b'', timeout=3)
    assert process.returncode == 2
    assert not stdout and not stderr


@pytest.mark.parametrize('normal,ignore_term', [(False, False), (False, True), (True, False)])
def test_timeout_and_normal_exit_clean_root_and_descendants(project, normal, ignore_term):
    pidfile = project / '.tram/local/descendant.json'
    child = 'import time,signal; ' + ('signal.signal(signal.SIGTERM,signal.SIG_IGN); ' if ignore_term else '') + 'time.sleep(30)'
    code = ('import subprocess,sys,time,json,os; from pathlib import Path; '
            'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]]); '
            'Path(sys.argv[1]).write_text(json.dumps({"pid":p.pid})); ' +
            ('time.sleep(.3)' if normal else 'time.sleep(30)'))
    configure(project, [sys.executable, '-c', code, str(pidfile), child], commands=[{
        'id': 'test', 'argv': [sys.executable, '-c', code, str(pidfile), child],
        'cwd': '.', 'confirmed': True, 'required': True, 'timeout': .7}])
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    try:
        result = tram.verify_run(project, 'sample', 'test')
        assert result['cleanup']['confirmed'] is True
        assert result['error'] == (None if normal else 'TIMEOUT')
        assert result['elapsed_ms'] < 6000
        descendant = json.loads(pidfile.read_text())['pid']
        assert descendant not in tram.process_table()
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_sigint_returns_130_and_cleans_child(project):
    ready = project / '.tram/local/ready'
    configure(project, [sys.executable, '-c', 'from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(30)', str(ready)])
    process = subprocess.Popen([sys.executable, str(RUNTIME), 'verify-run', '--project', str(project), '--slug', 'sample', '--command', 'test'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists()
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 130, stderr
        result = json.loads(stdout)
        assert result['execution_status'] == 'cancelled'
        assert result['result']['cleanup']['confirmed']
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_duplicate_command_reservation_blocks_second_execution(project):
    ready, release = project / '.tram/local/ready', project / '.tram/local/release'
    code = ('from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); '
            'deadline=time.monotonic()+4\nwhile not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.02)')
    configure(project, [sys.executable, '-c', code, str(ready), str(release)])
    process = subprocess.Popen([sys.executable, str(RUNTIME), 'verify-run', '--project', str(project), '--slug', 'sample', '--command', 'test'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists()
        blocked = cli(project, 'verify-run', '--slug', 'sample', '--command', 'test')
        assert blocked.returncode == 2
        assert json.loads(blocked.stdout)['errorCode'] == 'EXECUTION_ACTIVE'
    finally:
        release.touch()
        process.communicate(timeout=8)


def test_streams_are_hashed_fully_without_raw_persistence(project):
    count = 2 * 1024 * 1024
    configure(project, [sys.executable, '-c', 'import os,sys; n=int(sys.argv[1]); os.write(1,b"A"*n); os.write(2,b"B"*n)', str(count)])
    result = tram.verify_run(project, 'sample', 'test')
    assert result['stdout_digest'] == hashlib.sha256(b'A' * count).hexdigest()
    assert result['stderr_digest'] == hashlib.sha256(b'B' * count).hexdigest()
    assert result['output']['stdout'] == {'bytes': count, 'truncated': True}
    assert result['diagnostics_status'] == 'disabled'
    assert not (project / '.tram/local/diagnostics').exists()
    assert 'AAAA' not in (project / '.tram/tasks/sample.json').read_text()


def test_masked_diagnostics_are_bounded_private_and_queries_do_not_prune(project):
    secret = 'unique-super-secret-value'
    payload = 'x' * 8187 + '\ntoken=' + secret + '\n' + 'z' * 300000
    configure(project, [sys.executable, '-c', 'import sys;sys.stdout.write(sys.argv[1])', payload],
              diagnostics={**tram.DIAGNOSTICS, 'enabled': True})
    result = tram.verify_run(project, 'sample', 'test')
    path = project / '.tram/local/diagnostics' / result['id']
    data = (path / 'stdout.log').read_bytes()
    assert secret.encode() not in data
    assert b'[REDACTED]' in data
    assert len(data) <= 262144
    assert (path.stat().st_mode & 0o777) == 0o700
    assert ((path / 'stdout.log').stat().st_mode & 0o777) == 0o600
    before = tree(project)
    assert tram.diagnostics(project, 'show', result['id'])['writes'] is False
    assert tree(project) == before
    manifest = path / 'manifest.json'
    value = json.loads(manifest.read_text())
    value['created_epoch'] = 0
    manifest.write_text(json.dumps(value))
    tram.status(project, 'sample')
    assert path.exists()
    assert result['id'] in tram.diagnostics(project, 'prune')['removed']


def test_diagnostic_symlink_is_unavailable_without_affecting_command(project, tmp_path):
    target = project / 'outside'
    target.mkdir()
    (project / '.tram/local/diagnostics').symlink_to(target, target_is_directory=True)
    configure(project, diagnostics={**tram.DIAGNOSTICS, 'enabled': True})
    result = tram.verify_run(project, 'sample', 'test')
    assert result['execution_status'] == 'succeeded'
    assert result['diagnostics_status'] == 'unavailable'
    assert not list(target.iterdir())


def test_new_defaults_prune_nested_caches_but_actual_changes_have_reasons(tmp_path):
    tram.init(tmp_path)
    (tmp_path / 'code.py').write_text('a')
    tram.start(tmp_path, 'sample', 'quick')
    state, config = tram.task(tmp_path, 'sample'), tram.profile(tmp_path)
    before = tram.fingerprint(tmp_path, config, state)
    cache = tmp_path / 'nested/.pytest_cache'
    cache.mkdir(parents=True)
    (cache / 'state').write_text('cache')
    assert tram.fingerprint(tmp_path, config, state) == before
    (tmp_path / 'code.py').write_text('b')
    (tmp_path / 'new.py').write_text('new')
    after = tram.fingerprint(tmp_path, config, state)
    reasons = tram.snapshot_changes(before, after)['paths']
    assert {'path': 'code.py', 'reason': 'content'} in reasons
    assert {'path': 'new.py', 'reason': 'added'} in reasons
    os.chmod(tmp_path / 'code.py', 0o755)
    assert {'path': 'code.py', 'reason': 'executable'} in tram.snapshot_changes(after, tram.fingerprint(tmp_path, config, state))['paths']
    (tmp_path / 'new.py').unlink()
    assert {'path': 'new.py', 'reason': 'removed'} in tram.snapshot_changes(after, tram.fingerprint(tmp_path, config, state))['paths']
    error('INPUT_EXCLUDE_CONFLICT', configure, tmp_path, inputs=['nested/.pytest_cache/state'], exclude=['**/.pytest_cache/**'])


def test_snapshot_changes_limit_and_streaming_hash(project):
    old = {'files': {}}
    new = {'files': {str(i): {'digest': 'x'} for i in range(120)}}
    result = tram.snapshot_changes(old, new)
    assert result['total'] == 120 and result['truncated'] and len(result['paths']) == 100
    (project / 'code.py').write_bytes(b'big\n' * 1000000)
    original = Path.read_bytes
    def no_large_read(path):
        if path.name == 'code.py':
            raise AssertionError('fingerprint must stream large content')
        return original(path)
    with patch.object(Path, 'read_bytes', no_large_read):
        tram.fingerprint(project, tram.profile(project), tram.task(project, 'sample'))


def test_metrics_complete_pending_resume_reopen_and_explicit_failure(project):
    since, until = '2000-01-01T00:00:00Z', '2100-01-01T00:00:00Z'
    first = tram.start(project, 'sample')
    second = tram.start(project, 'sample')
    assert first['resume_id'] == second['resume_id']
    summary = tram.metrics(project, 'summary', since, until)
    assert summary['tasks']['pending'] == 1
    assert summary['resumes']['pending'] == 1
    assert summary['tasks']['completion_rate'] is None
    assert summary['cost'] is None and summary['tokens'] is None
    configure(project, [sys.executable, '-c', 'raise SystemExit(7)'])
    tram.verify_run(project, 'sample', 'test')
    assert tram.metrics(project, 'summary', since, until)['tasks']['failed'] == 0
    configure(project)
    tram.verify_run(project, 'sample', 'test')
    tram.transition(project, 'sample', 'complete')
    summary = tram.metrics(project, 'summary', since, until)
    assert summary['tasks']['completion_rate'] == 1
    assert summary['resumes']['success_rate'] == 1
    before = tree(project)
    tram.metrics(project, 'events', since, until)
    tram.metrics(project, 'summary', since, until)
    assert tree(project) == before
    (project / 'code.py').write_text('changed')
    tram.start(project, 'sample')
    summary = tram.metrics(project, 'summary', since, until)
    assert summary['tasks']['pending'] == 1 and summary['tasks']['denominator'] == 0
    error('REFERENCE_REQUIRED', tram.metrics, project, 'task-close', slug='sample', outcome='failed')
    result = tram.metrics(project, 'task-close', slug='sample', outcome='failed', reference='user-session:1', reason_code='user-stopped')
    assert result['recorded']
    assert tram.task(project, 'sample')['phase'] == 'verifying'
    assert tram.metrics(project, 'summary', since, until)['tasks']['completion_rate'] == 0
    assert tram.metrics(project, 'task-close', slug='sample', outcome='failed', reference='user-session:1', reason_code='user-stopped')['idempotent']
    tram.verify_run(project, 'sample', 'test')
    assert tram.metrics(project, 'summary', since, until)['tasks']['pending'] == 1


def test_metrics_disable_purge_question_and_host_measurement(project):
    result = tram.metrics(project, 'question-assessment', slug='sample', question_id='Q1', assessment='unknown', evidence_type='review', evidence_path='code.py')
    assert result['recorded']
    tram.metrics(project, 'host-measurement', slug='sample', cost=1.5, tokens=42, source='host-receipt:1')
    summary = tram.metrics(project, 'summary', '2000-01-01T00:00:00Z', '2100-01-01T00:00:00Z')
    assert summary['cost'] == 1.5 and summary['tokens'] == 42
    configure(project, metrics={**tram.METRICS, 'enabled': False})
    path = project / '.tram/local/metrics/events.jsonl'
    before = path.read_bytes()
    tram.start(project, 'sample')
    assert path.read_bytes() == before
    tram.metrics(project, 'purge')
    assert not path.exists()


def test_metrics_append_failure_does_not_rollback_real_transition(project):
    tram.verify_run(project, 'sample', 'test')
    with patch.object(tram, 'append_event', side_effect=OSError('full disk')):
        result = tram.transition(project, 'sample', 'complete')
    assert result['effective_phase'] == 'complete'
    assert result['metrics_recorded'] is False
    assert tram.task(project, 'sample')['phase'] == 'complete'


def test_observed_descendant_escape_is_reported_without_killing_it(project):
    marker = project / '.tram/local/escaped'
    child = ('import os,time,sys;from pathlib import Path;time.sleep(.35);os.setsid();'
             'Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(10)')
    root = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[2],sys.argv[1]]);time.sleep(30)')
    argv = [sys.executable, '-c', root, str(marker), child]
    configure(project, commands=[{'id': 'test', 'argv': argv, 'cwd': '.', 'confirmed': True, 'required': True, 'timeout': 1}])
    pid = None
    try:
        result = tram.verify_run(project, 'sample', 'test')
        pid = int(marker.read_text())
        assert result['error'] == 'PROCESS_CLEANUP_FAILED'
        assert pid in result['cleanup']['unresolved']
        assert pid in tram.process_table()
        assert tram.active_runs(project, 'sample')
    finally:
        # The test-created escaped fixture owns its PID file; the production detector received no PID injection.
        if pid is None and marker.exists():
            pid = int(marker.read_text())
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_crash_after_result_before_task_evidence_can_register_once(project):
    program = '''import importlib.util,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.save
def crash(path,value,expected=None):
    if '/tasks/' in str(path) and value.get('verification'):
        os._exit(99)
    return original(path,value,expected)
m.save=crash
m.verify_run(Path(sys.argv[2]),'sample','test')
'''
    run = subprocess.run([sys.executable, '-c', program, str(RUNTIME), str(project)], capture_output=True, start_new_session=True, timeout=8)
    assert run.returncode == 99
    # os._exit left a dead writer lock and an unregistered, fully collected result.
    report = tram.recover(project)
    assert report['liveness'] == 'dead'
    assert report['runs'][0]['result']['execution_status'] == 'succeeded'
    tram.recover(project, 'apply', report['digest'], report['token'])
    evidence = tram.task(project, 'sample')['verification']
    assert len(evidence) == 1 and evidence[0]['recorded']
    assert not tram.active_runs(project)
    report = tram.recover(project)
    assert not report['runs']


def test_crash_before_spawn_is_recovered_as_unexecuted(project):
    program = '''import importlib.util,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.execute_owned=lambda *args: os._exit(88)
m.verify_run(Path(sys.argv[2]),'sample','test')
'''
    run = subprocess.run([sys.executable, '-c', program, str(RUNTIME), str(project)], capture_output=True, start_new_session=True, timeout=8)
    assert run.returncode == 88
    report = tram.recover(project)
    assert report['runs'][0]['state'] == 'reserved'
    assert 'child' not in report['runs'][0]
    tram.recover(project, 'apply', report['digest'], report['token'])
    assert tram.task(project, 'sample')['verification'] == []


def test_stream_masker_suffix_stays_bounded_and_redacts_long_secret():
    masker = tram.OutputMasker()
    output = bytearray()
    data = b'x' * 8188 + b'\nAuthorization: Bearer ' + b's' * 90000 + b'\nfinish\npassword=other-secret\n'
    for offset in range(0, len(data), 511):
        output.extend(masker.feed(data[offset:offset + 511]))
        assert len(masker.pending) <= 8192
    output.extend(masker.feed(b'', final=True))
    assert b's' * 32 not in output
    assert b'other-secret' not in output
    assert b'finish' in output and b'[REDACTED]' in output


@pytest.mark.parametrize('after_metadata', [False, True])
def test_crash_around_child_metadata_never_grants_execution(project, after_metadata):
    marker = project / '.tram/local/must-not-run'
    configure(project, [sys.executable, '-c', 'from pathlib import Path;import sys;Path(sys.argv[1]).touch()', str(marker)])
    program = '''import importlib.util,os,sys,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.atomic
def crash(path,data):
    value=json.loads(data) if '/runs/' in str(path) else {}
    if value.get('state')=='running':
        if sys.argv[3]=='after': original(path,data)
        os._exit(77)
    return original(path,data)
m.atomic=crash
m.verify_run(Path(sys.argv[2]),'sample','test')
'''
    run = subprocess.run([sys.executable, '-c', program, str(RUNTIME), str(project), 'after' if after_metadata else 'before'], capture_output=True, start_new_session=True, timeout=8)
    assert run.returncode == 77
    time.sleep(.3)
    assert not marker.exists()
    runs = tram.run_records(project)
    assert len(runs) == 1
    assert ('child' in runs[0][1]) is after_metadata
    if after_metadata:
        assert runs[0][1]['child']['pid'] not in tram.process_table()


def test_recovery_race_applies_dead_lock_once(project):
    dead = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    dead.wait()
    (project / '.tram/local/write.lock').write_text(json.dumps({'pid': dead.pid, 'start_id': 'dead', 'token': 'race'}))
    preview = tram.recover(project)
    args = [sys.executable, str(RUNTIME), 'recover', 'apply', '--project', str(project), '--expected-digest', preview['digest'], '--token', 'race']
    processes = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True) for _ in range(2)]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=8)
        results.append((process.returncode, json.loads(stdout)))
    assert sorted(code for code, _ in results) == [0, 2]
    assert next(value for code, value in results if code == 2)['errorCode'] == 'DIGEST_CONFLICT'
    assert not (project / '.tram/local/write.lock').exists()


def test_partial_migration_journal_can_restore_checked_backup(project):
    before = tram.profile(project)
    preview = tram.migrate(project, 'preview', 2, 1)
    original = tram.atomic
    failed = False
    def write_failure(path, data):
        nonlocal failed
        if str(path).endswith('.tram/installation.json') and not failed:
            failed = True
            raise OSError('injected disk error')
        return original(path, data)
    with patch.object(tram, 'atomic', write_failure):
        with pytest.raises(OSError):
            tram.migrate(project, 'apply', 2, 1, preview['digest'])
    manifests = list((project / '.tram/local/backups/migration').glob('*/manifest.json'))
    manifest = json.loads(manifests[0].read_text())
    assert manifest['status'] == 'partial'
    assert set(manifest['journal'].values()) == {'pending', 'applied'}
    report = tram.restore(project, 'preview', manifest['id'])
    tram.restore(project, 'apply', manifest['id'], report['digest'])
    assert tram.profile(project)['schema_version'] == 2
    assert tram.profile(project)['inputs'] == before['inputs']
    assert tram.task(project, 'sample')['blocked'] == 'migration/restore 이후 재검증 필요'


def test_metrics_half_open_period_and_pending_exclusion(project):
    path = project / '.tram/local/metrics/events.jsonl'
    events = [
        {'id': '1', 'type': 'task_started', 'slug': 'sample', 'episode_id': 'a', 'timestamp': '2026-01-01T00:00:00+00:00'},
        {'id': '2', 'type': 'task_closed', 'slug': 'sample', 'episode_id': 'a', 'outcome': 'complete', 'timestamp': '2026-01-02T00:00:00+00:00'},
        {'id': '3', 'type': 'reopened', 'slug': 'sample', 'episode_id': 'b', 'timestamp': '2026-01-03T00:00:00+00:00'},
    ]
    path.write_bytes(b''.join(tram.canonical(e) + b'\n' for e in events))
    summary = tram.metrics(project, 'summary', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
    assert summary['tasks']['denominator'] == 0
    summary = tram.metrics(project, 'summary', '2026-01-02T00:00:00Z', '2026-01-03T00:00:00Z')
    assert summary['tasks']['completion_rate'] == 1
    summary = tram.metrics(project, 'summary', '2026-01-01T00:00:00Z', '2026-01-04T00:00:00Z')
    assert summary['tasks']['pending'] == 1 and summary['tasks']['denominator'] == 0


def test_metrics_retention_prunes_closed_but_keeps_pending_and_active(project):
    path = project / '.tram/local/metrics/events.jsonl'
    events = [
        {'id': '1', 'type': 'task_started', 'slug': 'old', 'episode_id': 'a', 'timestamp': '2000-01-01T00:00:00+00:00'},
        {'id': '2', 'type': 'task_closed', 'slug': 'old', 'episode_id': 'a', 'outcome': 'failed', 'timestamp': '2000-01-02T00:00:00+00:00'},
        {'id': '3', 'type': 'task_started', 'slug': 'sample', 'episode_id': 'b', 'timestamp': '2000-01-03T00:00:00+00:00'},
    ]
    path.write_bytes(b''.join(tram.canonical(e) + b'\n' for e in events))
    assert tram.metrics(project, 'prune')['removed'] == 2
    retained = tram.read_events(project)
    assert any(e['id'] == '3' for e in retained)
    summary = tram.metrics(project, 'summary', '2000-01-01T00:00:00Z', '2100-01-01T00:00:00Z')
    assert summary['coverage']['retention_truncated']
    assert summary['tasks']['pending'] == 1


def test_unknown_process_observation_refuses_command_without_kill(project):
    marker = project / '.tram/local/not-started'
    configure(project, [sys.executable, '-c', 'from pathlib import Path;import sys;Path(sys.argv[1]).touch()', str(marker)])
    with patch.object(tram, 'process_identity', return_value=None), patch.object(tram.os, 'killpg') as kill_group:
        result = tram.verify_run(project, 'sample', 'test')
    assert result['execution_status'] == 'failed'
    assert result['error'] == 'PROCESS_OBSERVATION_FAILED'
    assert result['cleanup']['confirmed']
    assert not marker.exists()
    kill_group.assert_not_called()


def test_pid_reuse_is_not_considered_live_owner(project):
    owner = {'pid': os.getpid(), 'start_id': 'different-start', 'token': 'old-generation'}
    assert tram.owner_state(owner) == 'dead'
    assert tram.owner_state({'pid': os.getpid()}) == 'unknown'


def test_recording_failure_preserves_collected_execution_result(project):
    original = tram.save
    def disk_failure(path, value, expected=None):
        if '/tasks/' in str(path) and value.get('verification'):
            raise OSError('simulated full disk')
        return original(path, value, expected)
    with patch.object(tram, 'save', disk_failure):
        result = tram.verify_run(project, 'sample', 'test')
    assert result['execution_status'] == 'succeeded'
    assert result['recorded'] is False
    assert result['registration_error'] == 'IO_ERROR'
    assert result['stdout_digest'] == hashlib.sha256(b'ok\n').hexdigest()
    assert tram.run_records(project)[0][1]['result']['exit_code'] == 0
    assert tram.task(project, 'sample')['verification'] == []


def test_status_reports_post_verification_change_paths(project):
    tram.verify_run(project, 'sample', 'test')
    (project / 'code.py').write_text('new source')
    view = tram.status(project, 'sample')
    assert {'path': 'code.py', 'reason': 'content'} in view['changes']['paths']


def test_escaped_continuous_pipe_writer_returns_bounded_incomplete_evidence(project):
    marker = project / '.tram/local/continuous-writer'
    child = '''import os,sys,time,threading
from pathlib import Path
time.sleep(.3)
os.setsid()
Path(sys.argv[1]).write_text(str(os.getpid()))
def emit(fd):
    try:
        while True: os.write(fd,b'x'*65536)
    except (BrokenPipeError,OSError): pass
threading.Thread(target=emit,args=(2,),daemon=True).start()
emit(1)
'''
    root = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[2],sys.argv[1]]);time.sleep(30)'
    argv = [sys.executable, '-c', root, str(marker), child]
    configure(project, commands=[{'id': 'test', 'argv': argv, 'cwd': '.', 'confirmed': True, 'required': True, 'timeout': .9}])
    process = subprocess.Popen([sys.executable, str(RUNTIME), 'verify-run', '--project', str(project), '--slug', 'sample', '--command', 'test'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    started = time.monotonic()
    try:
        stdout, stderr = process.communicate(timeout=7)
        assert time.monotonic() - started < 7, stderr
        result = json.loads(stdout)['result']
        assert result['execution_status'] == 'cleanup_failed'
        assert result['output_complete'] is False
        assert result['partial_output_digests']
        for name, complete in result['stream_complete'].items():
            if not complete:
                assert result[name + '_digest'] is None
                assert result['output_incomplete_reason'][name] in ('byte_limit', 'time_limit', 'pipe_open_without_eof')
        assert not result['cleanup']['confirmed']
        assert 'COMMAND_EVIDENCE_MISSING:test' in tram.status(project, 'sample')['completion_issues']
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if marker.exists():
            pid = int(marker.read_text())
            entry = tram.process_table().get(pid)
            # Only the fixture-created setsid session may be cleaned by this test.
            if entry and entry['sid'] == pid and entry['pgid'] == pid:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


def crash_two_unregistered_runs(project):
    commands = [{'id': name, 'argv': [sys.executable, '-c', 'import time;time.sleep(.4);print("' + name + '")'],
                 'cwd': '.', 'confirmed': True, 'required': True, 'timeout': 3} for name in ('one', 'two')]
    configure(project, commands=commands)
    program = '''import importlib.util,os,sys,time,json,concurrent.futures
from pathlib import Path
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(sys.argv[2]);original=m.save
def crash(path,value,expected=None):
    if '/tasks/' in str(path) and value.get('verification'):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            results=[r for _,r in m.run_records(root) if r.get('result')]
            if len(results)==2: os._exit(99)
            time.sleep(.02)
        os._exit(98)
    return original(path,value,expected)
m.save=crash
def execute(name):
    deadline=time.monotonic()+5
    while True:
        try: return m.verify_run(root,'sample',name)
        except m.TramError as exc:
            if exc.code!='LOCKED' or time.monotonic()>=deadline: raise
            time.sleep(.02)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    jobs=[pool.submit(execute,name) for name in ('one','two')]
    for job in jobs: job.result()
'''
    process = subprocess.run([sys.executable, '-c', program, str(RUNTIME), str(project)], capture_output=True, start_new_session=True, timeout=9)
    assert process.returncode == 99, process.stderr.decode()
    report = tram.recover(project)
    assert len(report['runs']) == 2
    assert {r['command_id'] for r in report['runs']} == {'one', 'two'}
    assert all(not r['recorded'] and r['result']['exit_code'] == 0 for r in report['runs'])
    assert tram.task(project, 'sample')['verification'] == []
    return report


def test_recover_accumulates_two_concurrent_results_and_marks_both_once(project):
    report = crash_two_unregistered_runs(project)
    tram.recover(project, 'apply', report['digest'], report['token'])
    records = tram.task(project, 'sample')['verification']
    assert {r['command_id'] for r in records} == {'one', 'two'}
    assert len({r['run_id'] for r in records}) == 2
    assert all(r['recorded'] for _, r in tram.run_records(project))
    assert not tram.recover(project)['runs']
    error('DIGEST_CONFLICT', tram.recover, project, 'apply', report['digest'], report['token'])
    assert len(tram.task(project, 'sample')['verification']) == 2


def test_recover_batch_interruption_after_task_write_is_idempotent(project):
    report = crash_two_unregistered_runs(project)
    original = tram.atomic
    failed = False
    def fail_run_marker(path, data):
        nonlocal failed
        if '/runs/' in str(path) and not failed:
            failed = True
            raise OSError('interrupted before marking run recorded')
        return original(path, data)
    with patch.object(tram, 'atomic', fail_run_marker):
        with pytest.raises(OSError):
            tram.recover(project, 'apply', report['digest'], report['token'])
    records = tram.task(project, 'sample')['verification']
    assert {r['command_id'] for r in records} == {'one', 'two'}
    journal = list((project / '.tram/local/backups/recovery').glob('*/manifest.json'))
    manifest = json.loads(journal[0].read_text())
    assert manifest['status'] == 'partial'
    assert manifest['journal']['.tram/tasks/sample.json'] == 'applied'
    assert not any(r['recorded'] for _, r in tram.run_records(project))
    retry = tram.recover(project)
    tram.recover(project, 'apply', retry['digest'], retry['token'])
    assert len(tram.task(project, 'sample')['verification']) == 2
    assert all(r['recorded'] for _, r in tram.run_records(project))


def test_recover_batch_revision_conflict_changes_no_runs(project):
    report = crash_two_unregistered_runs(project)
    task_path = project / '.tram/tasks/sample.json'
    state = json.loads(task_path.read_text())
    state['revision'] += 1
    task_path.write_text(json.dumps(state))
    error('STALE_RUN_RESULT', tram.recover, project, 'apply', report['digest'], report['token'])
    assert not any(r['recorded'] for _, r in tram.run_records(project))
    assert tram.task(project, 'sample')['verification'] == []


def diagnose(root):
    before = tree(root)
    with patch.object(tram, 'release_adapter', return_value='codex'), patch('socket.socket.connect', side_effect=AssertionError('network')):
        result = tram.doctor(root)
    assert tree(root) == before
    assert result['writes'] is False
    assert result['next_action'] == result['readiness']['next_action']
    assert all(set(i) == {'code', 'severity', 'evidence', 'message', 'next_action'} for i in result['readiness']['issues'])
    return result


def test_readiness_ready_preserves_status_and_raw_fields(project):
    before = tram.status(project, 'sample')
    report = diagnose(project)
    assert report['readiness']['status'] == 'ready'
    assert 'start' in report['next_action']
    assert 'recover' not in report['next_action'] and 'migrate' not in report['next_action']
    assert isinstance(report['files'], list) and report['lock'] is None and report['active_runs'] == []
    assert report['runtime'] == {'version': tram.release_version(), 'adapter': 'codex', 'project_schema': 2,
                                 'package_identity': 'unknown', 'host_validation': 'unknown'}
    assert tram.status(project, 'sample') == before


def test_readiness_missing_and_partial_connection(tmp_path, project):
    empty = tmp_path / 'empty'
    empty.mkdir()
    report = diagnose(empty)
    assert report['readiness']['issues'][0]['code'] == 'PROJECT_NOT_CONNECTED'
    assert report['runtime']['project_schema'] == 'unknown'
    (project / '.tram/installation.json').unlink()
    report = diagnose(project)
    assert report['readiness']['issues'][0]['code'] == 'INSTALLATION_MISSING'
    (project / '.tram/project.json').write_text('{')
    report = diagnose(project)
    assert report['readiness']['issues'][0]['code'] == 'STATE_UNREADABLE'
    assert not any(i['code'] == 'PROJECT_NOT_CONNECTED' for i in report['readiness']['issues'])


@pytest.mark.parametrize('liveness', ['live', 'unknown', 'dead'])
@pytest.mark.parametrize('kind', ['lock', 'run'])
def test_readiness_owner_priority_and_legacy(project, liveness, kind):
    path = project / '.tram/project.json'
    config = json.loads(path.read_text())
    config['schema_version'] = 1
    path.write_text(json.dumps(config))
    if kind == 'lock':
        path = project / '.tram/local/write.lock'
        value = {'pid': 123, 'start_id': 'fixture'}
    else:
        path = project / '.tram/local/runs/run.json'
        path.parent.mkdir(exist_ok=True)
        value = {'id': 'run', 'slug': 'sample', 'command_id': 'test', 'state': 'running',
                 'parent': {'pid': 123, 'start_id': 'fixture'}, 'recorded': False}
    path.write_text(json.dumps(value))
    with patch.object(tram, 'owner_state', return_value=liveness):
        report = diagnose(project)
        assert report == diagnose(project)
    assert report['readiness']['status'] == 'blocked'
    assert report['readiness']['issues'][0]['code'] == ('DEAD_OWNER' if liveness == 'dead' else 'OWNER_ACTIVE_OR_UNKNOWN')
    assert any(i['code'] == 'LEGACY_SCHEMA' for i in report['readiness']['issues'])
    if liveness != 'dead':
        assert 'recover' not in report['next_action'] and 'migrate' not in report['next_action']


@pytest.mark.parametrize('schema', [1, 3, True, None])
def test_readiness_mixed_schema(project, schema):
    path = project / '.tram/tasks/sample.json'
    value = json.loads(path.read_text())
    value['schema_version'] = schema
    path.write_text(json.dumps(value))
    report = diagnose(project)
    assert report['readiness']['status'] == 'blocked'
    issue = report['readiness']['issues'][0]
    assert issue['evidence']['path'] == '.tram/tasks/sample.json'
    assert issue['code'] == ('LEGACY_SCHEMA' if type(schema) is int and schema == 1 else 'STATE_UNREADABLE')


@pytest.mark.parametrize('kind', ['task', 'run', 'finished'])
def test_readiness_malformed_records_never_ready(project, kind):
    if kind == 'task':
        path = project / '.tram/tasks/sample.json'
        value = json.loads(path.read_text())
        value['approvals'] = None
    else:
        path = project / '.tram/local/runs/bad.json'
        path.parent.mkdir(exist_ok=True)
        value = {'state': 'finished'} if kind == 'finished' else {}
    path.write_text(json.dumps(value))
    report = diagnose(project)
    assert report['readiness']['status'] == 'blocked'
    assert any(i['code'] == 'STATE_UNREADABLE' for i in report['readiness']['issues'])


def test_readiness_finished_run_has_no_schema(project):
    tram.verify_run(project, 'sample', 'test')
    report = diagnose(project)
    assert report['readiness']['status'] == 'ready'
    assert report['active_runs'] == []
    assert all(e['readable'] for e in report['files'])


def test_readiness_config_limit_and_optional_tools(project):
    path = project / '.tram/project.json'
    value = json.loads(path.read_text())
    assert all(not value[k]['configured'] for k in ('coverage', 'perf', 'reviewer'))
    assert diagnose(project)['readiness']['status'] == 'ready'
    value['commands'][0]['confirmed'] = False
    path.write_text(json.dumps(value))
    report = diagnose(project)
    assert report['readiness']['status'] == 'attention'
    assert report['readiness']['issues'][0]['code'] == 'VERIFICATION_UNCONFIRMED'


@pytest.mark.parametrize('metadata', ['missing', 'broken'])
def test_readiness_metadata_failures_keep_diagnosis(project, tmp_path, metadata):
    package = tmp_path / 'package'
    (package / 'runtime').mkdir(parents=True)
    if metadata == 'broken':
        (package / 'release.json').write_text('{')
    (project / '.tram/project.json').write_text('{')
    before = tree(project)
    with patch.object(tram, '__file__', str(package / 'runtime/tram.py')):
        report = tram.doctor(project)
    assert tree(project) == before
    assert report['runtime']['version'] == report['runtime']['adapter'] == 'unknown'
    assert report['readiness']['issues'][0]['code'] == 'STATE_UNREADABLE'
    assert len([i for i in report['readiness']['issues'] if i['code'] == 'RUNTIME_METADATA_UNKNOWN']) == 2


def test_readiness_damage_precedes_dead_owner_and_missing(project):
    (project / '.tram/project.json').unlink()
    (project / '.tram/tasks/sample.json').write_text('{')
    (project / '.tram/local/write.lock').write_text('{}')
    with patch.object(tram, 'owner_state', return_value='dead'):
        report = diagnose(project)
    assert [i['code'] for i in report['readiness']['issues']] == ['STATE_UNREADABLE', 'DEAD_OWNER', 'PROJECT_NOT_CONNECTED']


def test_readiness_cli_readonly_and_input_errors(project, tmp_path):
    before = tree(project)
    run = cli(project, 'doctor')
    assert run.returncode == 0
    report = json.loads(run.stdout)['result']
    assert report['writes'] is False and 'runtime' in report and 'readiness' in report
    assert tree(project) == before
    missing = cli(tmp_path / 'absent', 'doctor')
    assert missing.returncode == 2
    assert json.loads(missing.stdout)['errorCode'] == 'PROJECT_NOT_FOUND'


@pytest.mark.parametrize('relative', ['.tram/project.json', '.tram/installation.json', '.tram/tasks/sample.json'])
def test_readiness_missing_revision_is_damage(project, relative):
    path = project / relative
    value = json.loads(path.read_text())
    del value['revision']
    path.write_text(json.dumps(value))
    report = diagnose(project)
    assert report['readiness']['issues'][0]['code'] == 'STATE_UNREADABLE'


def test_readiness_partial_installation_object_and_schema_type(project):
    (project / '.tram/installation.json').write_text(json.dumps({'schema_version': 2, 'linked': True, 'revision': 1}))
    report = diagnose(project)
    assert report['readiness']['status'] == 'blocked'
    path = project / '.tram/project.json'
    value = json.loads(path.read_text())
    value['schema_version'] = {'invalid': 2}
    path.write_text(json.dumps(value))
    assert diagnose(project)['runtime']['project_schema'] == 'unknown'


def test_readiness_unreadable_profile_is_not_missing(project):
    original = tram.raw_json
    def read(root, relative):
        if relative == '.tram/project.json':
            raise PermissionError('fixture read denied')
        return original(root, relative)
    with patch.object(tram, 'raw_json', side_effect=read):
        report = diagnose(project)
    assert report['readiness']['issues'][0]['evidence']['errorCode'] == 'IO_ERROR'
    assert not any(i['code'] == 'PROJECT_NOT_CONNECTED' for i in report['readiness']['issues'])
    assert report['runtime']['project_schema'] == 'unknown'


def test_readiness_cli_keeps_path_escape_error(project, tmp_path):
    path = project / '.tram/project.json'
    outside = tmp_path.parent / (tmp_path.name + '-outside.json')
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    before = tree(project)
    # A file-level escape is accumulated; root traversal still uses the original error contract.
    report = cli(project, 'doctor')
    assert report.returncode == 0
    value = json.loads(report.stdout)['result']
    assert any(e.get('errorCode') == 'SYMLINK' for e in value['files'])
    assert value['readiness']['status'] == 'blocked'
    assert tree(project) == before
