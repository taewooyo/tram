"""패키지 본체와 대상 프로젝트를 분리한 실제 subprocess 계약 검사."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'src'


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'target project'
        self.root.mkdir()
        self.tool = Path(self.temp.name) / 'package'
        for folder in ('hooks', 'scripts', 'templates'):
            shutil.copytree(SOURCE / folder, self.tool / folder)
        self.write('.gitignore', '.tram/local/\n')
        self.profile({'schema_version': 1, 'contextMappings': []})

    def write(self, path, text):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding='utf-8')
        return destination

    def profile(self, data):
        self.write('.tram/project.json', json.dumps(data))

    def hook(self, name, tool_input=None, **payload):
        data = {'cwd': str(self.root), 'session_id': 'session',
                'hook_event_name': 'PreToolUse', 'tool_input': tool_input or {}}
        data.update(payload)
        env = dict(os.environ, CODEX_PROJECT_DIR='/nonexistent', CLAUDE_PROJECT_DIR='/nonexistent')
        return subprocess.run(['bash', str(self.tool / 'hooks' / name)],
                              input=json.dumps(data), text=True, capture_output=True,
                              cwd=self.tool, env=env)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_context_payload_root_patch_dedup(self):
        self.write('cards/rules.md', 'PROJECT RULES')
        self.profile({'schema_version': 1, 'contextMappings': [{'path': 'app/*', 'card': 'cards/rules.md'}]})
        result = self.hook('inject-context.sh', {'command': '*** Begin Patch\n*** Update File: app/a.py\n*** Add File: app/b.py'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PROJECT RULES', result.stdout)
        self.assertEqual(self.hook('inject-context.sh', {'file_path': 'app/a.py'}).stdout, '')
        self.assertTrue((self.root / '.tram/local/markers').is_dir())
        self.assertFalse((self.tool / '.tram').exists())

    def test_new_profile_has_no_android_fallback(self):
        result = self.hook('inject-context.sh', {'file_path': 'app/a.kt'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_context_supported_schemas_inject_and_invalid_versions_reject(self):
        self.write('cards/rules.md', 'SCHEMA RULES')
        mapping = [{'path': 'app/*', 'card': 'cards/rules.md'}]
        for field, version, mappings in (
                ('schema_version', 1, 'conventions'),
                ('schema_version', 2, 'conventions'),
                ('version', 1, 'contextMappings')):
            with self.subTest(field=field, version=version):
                self.profile({field: version, mappings: mapping})
                result = self.hook('inject-context.sh', {'file_path': 'app/a.py'}, session_id='')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                context = json.loads(result.stdout)['hookSpecificOutput']
                self.assertEqual(context['hookEventName'], 'PreToolUse')
                self.assertEqual(context['additionalContext'], 'SCHEMA RULES')
        for field in ('schema_version', 'version'):
            for version in (None, True, False, 0, 3, '1', '2', 1.0, 2.0):
                with self.subTest(field=field, version=version):
                    self.profile({field: version, 'conventions': mapping})
                    result = self.hook('inject-context.sh', {'file_path': 'app/a.py'}, session_id='')
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('schema 1 또는 2 필요', result.stderr)
        self.assertFalse((self.root / '.tram/local').exists())

    def test_context_rejects_outside_and_symlink_card(self):
        self.write('card.md', 'RULE')
        self.profile({'schema_version': 1, 'contextMappings': [{'path': '*', 'card': 'card.md'}]})
        self.assertEqual(self.hook('inject-context.sh', {'file_path': '../outside'}).stdout, '')
        (self.root / 'escape.md').symlink_to(self.tool / 'templates/pull_request_template.md')
        self.profile({'schema_version': 1, 'contextMappings': [{'path': '*', 'card': 'escape.md'}]})
        result = self.hook('inject-context.sh', {'file_path': 'app/a'})
        self.assertEqual(result.stdout, '')
        self.assertIn('바깥', result.stderr)

    def test_legacy_profile_and_new_precedence(self):
        self.write('card.md', 'LEGACY')
        self.write('.codex/project-profile.json', json.dumps({'version': 1, 'contextMappings': [{'path': '*', 'card': 'card.md'}]}))
        self.assertEqual(self.hook('inject-context.sh', {'file_path': 'app/a'}).stdout, '')
        (self.root / '.tram/project.json').unlink()
        self.assertIn('LEGACY', self.hook('inject-context.sh', {'file_path': 'app/a'}).stdout)

    def test_domain_multi_patch_and_large_tier(self):
        self.write('docs/domain/_territory.tsv', 'app/* orders\n')
        self.write('docs/domain/orders.md', '\n'.join(f'line {n}' for n in range(90)))
        self.write('docs/domain/README.md', 'INDEX')
        result = self.hook('inject-domain.sh', {'patch': '*** Update File: app/a\n*** Update File: app/b'})
        self.assertIn('INDEX', result.stdout)
        self.assertIn('line 15', result.stdout)
        self.assertNotIn('line 80', result.stdout)
        self.assertEqual(self.hook('inject-domain.sh', {'file_path': 'app/a'}).stdout, '')

    def test_usage_explicit_events_and_sanitization(self):
        self.hook('usage-log.sh', prompt='/retro secret', hook_event_name='Status')
        self.assertFalse((self.root / '.tram/local').exists())
        self.hook('usage-log.sh', prompt='/tram:retro secret', hook_event_name='UserPromptSubmit')
        log = self.root / '.tram/local/logs/skill-usage.log'
        self.assertTrue(log.read_text().endswith('\tretro\n'))
        self.assertNotIn('secret', log.read_text())
        before = log.read_bytes()
        self.hook('usage-log.sh', {'skill': 'retro\nforged'}, tool_name='Skill')
        self.assertEqual(before, log.read_bytes())

    def test_local_ignore_required(self):
        (self.root / '.gitignore').unlink()
        self.hook('usage-log.sh', {'skill': 'retro'}, tool_name='Skill')
        self.assertFalse((self.root / '.tram/local').exists())

    def test_pr_body_file_actual_content_target_template(self):
        self.write('.github/pull_request_template.md', '## Custom\n```mermaid\n')
        self.write('body.md', '## Custom\n```mermaid\nflowchart LR\n```\n')
        result = self.hook('enforce-pr-template.sh', {'command': 'gh pr create --body-file body.md'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write('body.md', 'invalid')
        self.assertEqual(self.hook('enforce-pr-template.sh', {'command': 'gh pr create --body-file body.md'}).returncode, 2)
        self.assertEqual(self.hook('enforce-pr-template.sh', {'command': "echo 'gh pr create'"}).returncode, 0)

    def test_pr_fallback_and_complex_shell_boundary(self):
        self.write('body.md', (self.tool / 'templates/pull_request_template.md').read_text())
        self.assertEqual(self.hook('enforce-pr-template.sh', {'command': 'gh pr create --body-file=body.md'}).returncode, 0)
        result = self.hook('enforce-pr-template.sh', {'command': 'cd other && gh pr create --body-file body.md'})
        self.assertEqual(result.returncode, 2)
        self.assertIn('사전 검사', result.stderr)

    def test_retro_git_scope_and_policy(self):
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 0)
        self.assertFalse((self.root / '.tram/local').exists())
        self.git('init', '-q')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-qm', 'first')
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 0)
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-qm', 'second')
        # 원래 정책: 로그가 없으면 판단 불가로 통과.
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 0)
        self.write('.tram/local/logs/skill-usage.log', '2000-01-01 00:00:00\timpl\n')
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 2)
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'SKIP_RETRO_GATE=1 git push'}).returncode, 0)
        self.hook('usage-log.sh', {'skill': 'retro'}, tool_name='Skill')
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 0)

    def test_legacy_retro_marker_is_read_only(self):
        self.git('init', '-q')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-qm', 'first')
        marker = self.write('.codex/.retro-gate-marker', '2000-01-01 00:00:00\nold-head\n')
        self.write('.codex/skill-usage.log', '2099-01-01 00:00:00\tretro\n')
        before = marker.read_bytes()
        self.assertEqual(self.hook('enforce-retro-gate.sh', {'command': 'git push'}).returncode, 0)
        self.assertEqual(before, marker.read_bytes())
        self.assertTrue((self.root / '.tram/local/markers/retro-gate').exists())

    def test_coverage_new_unconfigured_legacy_python(self):
        script = self.tool / 'scripts/lib/coverage-profile.sh'
        def adapter():
            return subprocess.run(['bash', '-c', 'source "$1"; coverage_profile_adapter "$2"', 'bash', str(script), str(self.root)], text=True, capture_output=True)
        self.assertEqual(adapter().stdout.strip(), 'unconfigured')
        self.write('.codex/project-profile.json', '{"version":1}')
        self.assertEqual(adapter().stdout.strip(), 'unconfigured')
        (self.root / '.tram/project.json').unlink()
        self.assertEqual(adapter().stdout.strip(), 'python-pytest-cov')

    def test_core_only_python_and_shell_syntax(self):
        result = subprocess.run(['bash', str(self.tool / 'scripts/check-environment.sh'), 'core'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('✅ git', result.stdout)
        for script in self.tool.rglob('*.sh'):
            subprocess.run(['bash', '-n', str(script)], check=True)

    def test_runtime_conventions_territories_fields(self):
        self.write('rules.md', 'CONVENTION')
        self.write('docs/domain/orders.md', 'ORDERS')
        self.profile({'schema_version': 1,
                      'conventions': [{'path': 'app/*', 'card': 'rules.md'}],
                      'territories': [{'path': 'app/*', 'slug': 'orders'}]})
        self.assertIn('CONVENTION', self.hook('inject-context.sh', {'file_path': 'app/a'}).stdout)
        self.assertIn('ORDERS', self.hook('inject-domain.sh', {'file_path': 'app/a'}).stdout)

    def test_status_events_do_not_write(self):
        self.write('rules.md', 'RULE')
        self.profile({'schema_version': 1, 'conventions': [{'path': '*', 'card': 'rules.md'}]})
        for name in ('inject-context.sh', 'inject-domain.sh', 'enforce-retro-gate.sh', 'usage-log.sh'):
            self.hook(name, {'file_path': 'app/a', 'command': 'git push', 'skill': 'retro'}, hook_event_name='Status', tool_name='Skill')
        self.assertFalse((self.root / '.tram/local').exists())

    def test_environment_adapters_without_payload_cwd(self):
        for variable in ('CODEX_PROJECT_DIR', 'CLAUDE_PROJECT_DIR'):
            env = {k: v for k, v in os.environ.items() if k not in ('CODEX_PROJECT_DIR', 'CLAUDE_PROJECT_DIR')}
            env[variable] = str(self.root)
            result = subprocess.run(['bash', str(self.tool / 'hooks/usage-log.sh')],
                input=json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': '/retro private'}),
                env=env, cwd=self.tool, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len((self.root / '.tram/local/logs/skill-usage.log').read_text().splitlines()), 2)

    def test_git_ignore_negation_prevents_logger(self):
        self.git('init', '-q')
        self.write('.gitignore', '.tram/local/\n!.tram/local/\n!.tram/local/**\n')
        self.hook('usage-log.sh', {'skill': 'retro'}, tool_name='Skill')
        self.assertFalse((self.root / '.tram/local').exists())

    def test_symlink_local_directory_is_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.root / '.tram/local').symlink_to(outside, target_is_directory=True)
        self.hook('usage-log.sh', {'skill': 'retro'}, tool_name='Skill')
        self.assertEqual(list(outside.iterdir()), [])

    def test_kover_xml_union_preserved(self):
        report = self.write('report.xml', '<report><package name="p"><class name="p/C" sourcefilename="C.kt"/><sourcefile name="C.kt"><line nr="1" ci="1" mi="0"/><line nr="2" ci="0" mi="1"/></sourcefile></package></report>')
        result = subprocess.run(['python3', str(self.tool / 'scripts/lib/kover-report.py'), '--report', f'jvm={report}'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['combined']['percent'], 50)

    def test_real_runtime_init_profile_is_accepted(self):
        (self.root / '.tram/project.json').unlink()
        runtime = SOURCE / 'runtime/tram.py'
        result = subprocess.run(['python3', str(runtime), 'init', '--project', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        profile = json.loads((self.root / '.tram/project.json').read_text())
        self.assertEqual(profile['schema_version'], 2)
        self.assertEqual(profile['conventions'], [])
        self.assertEqual(profile['territories'], [])
        self.assertEqual(self.hook('inject-context.sh', {'file_path': 'app/a.kt'}).stdout, '')
        self.assertEqual(self.hook('inject-domain.sh', {'file_path': 'app/a.kt'}).stdout, '')
        self.write('rules.md', 'CURRENT SCHEMA CONVENTION')
        delta = self.write('configure.json', json.dumps({
            'conventions': [{'path': 'app/*', 'card': 'rules.md'}]}))
        configured = subprocess.run(['python3', str(runtime), 'configure', '--project', str(self.root),
                                     '--file', str(delta)], capture_output=True, text=True)
        self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
        context = self.hook('inject-context.sh', {'file_path': 'app/a.kt'})
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertEqual(json.loads(context.stdout)['hookSpecificOutput']['additionalContext'],
                         'CURRENT SCHEMA CONVENTION')
        result = self.hook('usage-log.sh', {'skill': 'retro'}, tool_name='Skill')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / '.tram/local/logs/skill-usage.log').exists())


if __name__ == '__main__':
    unittest.main()
