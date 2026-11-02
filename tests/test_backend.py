import importlib.util
import pathlib
import unittest

import json
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / pathlib.Path(json.loads((ROOT / 'manifest.json').read_text())['entryPoints']['overlay']).parent
spec = importlib.util.spec_from_file_location("backend", RUNTIME / "backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

class BackendTests(unittest.TestCase):
    def setUp(self):
        import tempfile, os, json
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name)
        self.shim = self.home / 'bin'
        self.shim.mkdir()
        tool = self.shim / 'hyprctl'
        tool.write_bytes((ROOT / 'tests/hyprctl_fixture.py').read_bytes())
        tool.chmod(0o755)
        self.original = {
            'animations.enabled': True, 'animations.workspace_wraparound': False,
            'general.gaps_in': [2,3,4,5], 'general.gaps_out': [7,8,9,10],
            'general.border_size': 4, 'decoration.rounding': 11,
            'decoration.blur.enabled': True, 'decoration.shadow.enabled': True,
            'decoration.screen_shader': '/old/example.frag', 'unrelated': 'keep'
        }
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        self.env = {'HOME': str(self.home), 'PATH': str(self.shim)+':/usr/bin',
                    'XDG_STATE_HOME': str(self.home / 'state'),
                    'HYPRLAND_INSTANCE_SIGNATURE': 'private_fixture_123',
                    'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

    def cli(self, *args, extra=None):
        import subprocess, json
        p = subprocess.run(['/usr/bin/python3', str(RUNTIME / 'backend.py'), *args],
                           env=dict(self.env, **(extra or {})), capture_output=True, timeout=25)
        self.assertLess(len(p.stdout), 1048576)
        self.assertEqual(p.stderr, b'', p.stderr)
        return p.returncode, json.loads(p.stdout)

    def values(self):
        import json
        return json.loads((self.home / 'compositor.json').read_text())

    def test_restore_alias_restores_receipt_not_selected_row(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def test_receipt_restore_ignores_unavailable_custom_catalogue(self):
        import os
        for damage in ['corrupt', 'oversized', 'symlink', 'hardlink', 'public-directory', 'missing']:
            with self.subTest(damage=damage):
                self.setUp()  # Each damaged catalogue owns a fresh fake HOME.
                code, captured = self.cli('action', '--id', 'capture:current', '--verb', 'capture',
                                          '--apply', '--payload', '{"name":"Captured"}')
                self.assertEqual(code, 0, captured)
                ident = 'off' if backend.SLUG == 'motion-presets' else 'compact-coding'
                self.assertEqual(self.cli('action', '--id', ident, '--verb', 'apply', '--apply')[0], 0)
                path = next((self.home / 'state').rglob('transaction.json'))
                store = next((self.home / '.config').rglob('custom-presets.json'))
                clean = store.read_bytes()
                moved = self.home / 'saved-custom.json'
                if damage == 'corrupt':
                    store.write_text('[')
                elif damage == 'oversized':
                    store.write_bytes(b' ' * 65537)
                elif damage in ('symlink', 'hardlink'):
                    store.rename(moved)
                    store.symlink_to(moved) if damage == 'symlink' else os.link(moved, store)
                elif damage == 'public-directory':
                    store.parent.chmod(0o755)
                else:
                    store.unlink()
                before, receipt = self.values(), path.read_bytes()
                count = (self.home / 'eval-count').read_bytes()
                # Only the exact receipt-only Restore may bypass catalogue membership.
                for verb in ['apply', 'confirm', 'preview', 'favorite']:
                    code, result = self.cli('action', '--id', 'restore:last', '--verb', verb, '--apply')
                    self.assertNotEqual(code, 0, result)
                if damage != 'missing':
                    code, result = self.cli('action', '--id', ident, '--verb', 'apply', '--apply')
                    self.assertNotEqual(code, 0, result)
                    preset = {'version': 1, 'slug': backend.SLUG, 'name': 'Import',
                              'settings': {k: self.original[k] for k in backend.SCHEMA}}
                    code, result = self.cli('action', '--id', 'import:preset', '--verb', 'import',
                                            '--apply', '--payload', json.dumps(preset))
                    self.assertNotEqual(code, 0, result)
                self.assertEqual(self.values(), before)
                self.assertEqual(path.read_bytes(), receipt)
                self.assertEqual((self.home / 'eval-count').read_bytes(), count)
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertEqual(code, 0, result)
                self.assertEqual(self.values(), self.original)
                self.assertFalse(path.exists())
                if damage == 'missing':
                    self.assertFalse(store.exists())
                elif damage == 'symlink':
                    self.assertTrue(store.is_symlink())
                    self.assertEqual(moved.read_bytes(), clean)
                else:
                    expected = b'[' if damage == 'corrupt' else (b' ' * 65537 if damage == 'oversized' else clean)
                    self.assertEqual(store.read_bytes(), expected)

    def test_receipt_only_recovery_keeps_guards_with_corrupt_custom_store(self):
        import fcntl
        ident = 'off' if backend.SLUG == 'motion-presets' else 'compact-coding'
        self.assertEqual(self.cli('action', '--id', 'capture:current', '--verb', 'capture',
                                  '--apply', '--payload', '{"name":"Saved"}')[0], 0)
        self.assertEqual(self.cli('action', '--id', ident, '--verb', 'apply', '--apply')[0], 0)
        store = next((self.home / '.config').rglob('custom-presets.json'))
        store.write_text('[')
        path = next((self.home / 'state').rglob('transaction.json'))
        receipt, current = path.read_bytes(), self.values()
        count = (self.home / 'eval-count').read_bytes()
        def refused(message, extra=None):
            code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply', extra=extra)
            self.assertNotEqual(code, 0, result)
            self.assertIn(message, result['message'])
            self.assertEqual((self.home / 'eval-count').read_bytes(), count)
            self.assertEqual(store.read_text(), '[')
        refused('session', {'HYPRLAND_INSTANCE_SIGNATURE': ''})
        refused('0.56.2', {'FIXTURE_VERSION': '0.99.0'})
        with (path.parent / 'lock').open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            refused('progress')
        for invalid, message in [(b' ' * 65537, '64 KiB'), (b'{}', 'snapshot')]:
            path.write_bytes(invalid)
            refused(message)
            self.assertEqual(path.read_bytes(), invalid)
        path.write_bytes(receipt)
        key = next(iter(backend.SCHEMA))
        edited = dict(current)
        edited[key] = not current[key] if type(current[key]) is bool else [999] * 4
        (self.home / 'compositor.json').write_text(json.dumps(edited))
        refused('conflict')
        self.assertEqual(path.read_bytes(), receipt)
        self.assertEqual(self.values(), edited)
        (self.home / 'compositor.json').write_text(json.dumps(current))
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(path.exists())

    def test_legacy_oversized_preferences_cannot_block_confirmed_apply_or_restore(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True):
            prefs = backend.preferences.change(backend.SLUG, backend.PREFERENCE_SCHEMA, {})
        ids = [str(i).zfill(3) + 'x' * 200 for i in range(512)]
        prefs['collections'] = {'group-' + str(i): ids for i in range(16)}
        path = self.home / '.config/omarchy/lego' / backend.SLUG / 'preferences.json'
        raw = json.dumps(prefs).encode('utf-8')
        self.assertGreater(len(raw), 1048576)
        self.assertLess(len(raw), 16777216)
        path.write_bytes(raw)  # Legacy disk fixture, not a newly permitted oversized write.
        for command in ['preferences', 'catalog']:
            code, result = self.cli(command)
            self.assertNotEqual(code, 0, result)
            self.assertIn('limit', result['message'].lower())
        ident = backend.load_rows()[0]['id']
        code, result = self.cli('action', '--id', ident, '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertIn('warning', result['message'].lower())
        self.assertNotEqual(self.values(), self.original)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertEqual(path.read_bytes(), raw)

    def test_restore_alias_without_receipt_cannot_claim_success(self):
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('No snapshot', result['message'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'eval-count').exists())

    def test_restore_alias_is_exact_explicit_restore_only(self):
        for ident, verb, apply in [('restore:last', 'apply', True), ('restore:last', 'confirm', True),
                                   ('restore:last ', 'restore', True), ('restore:LAST', 'restore', True),
                                   ('restore:last', 'restore', False)]:
            args = ['action', '--id', ident, '--verb', verb] + (['--apply'] if apply else [])
            code, result = self.cli(*args)
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())
        self.assertEqual(self.values(), self.original)

    def test_restore_alias_preserves_external_edit_and_receipt(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        receipt = path.read_bytes()
        count = (self.home / 'eval-count').read_bytes()
        edited = self.values()
        key = next(iter(row['settings']))
        value = edited[key]
        edited[key] = not value if type(value) is bool else (99 if type(value) is int else ([99]*4 if type(value) is list else '/external.frag'))
        (self.home / 'compositor.json').write_text(json.dumps(edited))
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('conflict', result['message'].lower())
        self.assertEqual(self.values(), edited)
        self.assertEqual(path.read_bytes(), receipt)
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)

    def test_restore_alias_requires_valid_bounded_session_receipt(self):
        import copy, json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        good = json.loads(path.read_text())
        invalid = []
        missing_id = dict(good); del missing_id['id']; invalid.append(missing_id)
        invalid.extend([dict(good, id=[]), dict(good, instance='foreign_session'), dict(good, phase='bad')])
        bad_values = copy.deepcopy(good); bad_values['before']['exec'] = 'bad'; invalid.append(bad_values)
        contents = [json.dumps(record).encode() for record in invalid] + [b' ' * 65537]
        before, count = self.values(), (self.home / 'eval-count').read_bytes()
        for content in contents:
            with self.subTest(receipt=content[:80]):
                path.write_bytes(content)
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(self.values(), before)
                self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        path.write_text(json.dumps(good))
        moved = self.home / 'owned-receipt.json'; path.rename(moved); path.symlink_to(moved)
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(moved.read_text()), good)
        self.assertEqual(self.values(), before)

    def test_explicit_apply_then_restore_actual_values(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_partial_failure_rolls_back_actual_values(self):
        row = backend.load_rows()[0]
        fail = '2' if backend.SLUG == 'workspace-profiles' else '1'
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FAIL_AT': fail, 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertFalse(result['ok'])
        self.assertEqual(self.values(), self.original, 'partial mutation was not rolled back')
        self.assertIn('rollback', result['message'].lower())

    def test_external_edits_block_restore_without_clobbering(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        changed = self.values()
        key = next(iter(row['settings']))
        changed[key] = not changed[key] if type(changed[key]) is bool else (99 if type(changed[key]) is int else ([99]*4 if type(changed[key]) is list else '/external.frag'))
        (self.home / 'compositor.json').write_text(json.dumps(changed))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('conflict', result['message'].lower())
        self.assertEqual(self.values(), changed)

    def test_unknown_membership_and_verb_have_no_ipc(self):
        for ident, verb in [('../evil', 'apply'), ('$(bad)', 'apply'), (backend.load_rows()[0]['id'], 'launch')]:
            code, result = self.cli('action', '--id', ident, '--verb', verb, '--apply')
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())

    def test_catalog_has_no_state_or_ipc_side_effects(self):
        code, result = self.cli('catalog')
        self.assertEqual(code, 0)
        self.assertEqual(result['rows'], backend.catalog()['rows'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())

    def test_unqualified_version_fails_closed(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_VERSION': '0.99.0'})
        self.assertNotEqual(code, 0)
        self.assertIn('0.56.2', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_missing_session_fails_closed(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'HYPRLAND_INSTANCE_SIGNATURE': ''})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'calls.jsonl').exists())

    def test_missing_helper_reports_failure(self):
        (self.shim / 'hyprctl').unlink()
        # PATH remains fixture-only to exclude the real executable even inside this isolated box.
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'PATH': str(self.shim)})
        self.assertNotEqual(code, 0)
        self.assertIn('unavailable', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_failed_rollback_retains_recoverable_snapshot(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FAILS': '1,2', 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('retained', result['message'].lower())
        self.assertEqual(len(list((self.home / 'state').rglob('transaction.json'))), 1)
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_interrupted_snapshot_restores_partial_transaction(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        record['phase'] = 'pending'
        record['previous'] = {k:self.original[k] for k in backend.SCHEMA}
        path.write_text(json.dumps(record))
        # Simulate a crash after only one field of a multi-field transaction was written.
        partial = self.values()
        keys = list(row['settings'])
        for key in keys[1:]:
            partial[key] = self.original[key]
        (self.home / 'compositor.json').write_text(json.dumps(partial))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_busy_lock_refuses_without_mutation(self):
        import fcntl
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        lock = next((self.home / 'state').rglob('lock'))
        with lock.open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.values()
            code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
            self.assertNotEqual(code, 0)
            self.assertIn('progress', result['message'])
            self.assertEqual(self.values(), before)

    def test_invalid_snapshot_fields_fail_without_trace_or_mutation(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        record['before']['exec'] = 'bad'
        path.write_text(json.dumps(record))
        before = self.values()
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('snapshot', result['message'])
        self.assertEqual(self.values(), before)

    def test_successive_presets_keep_original_restore_baseline(self):
        rows = backend.load_rows() if backend.SLUG != 'shader-deck' else backend.load_rows()[:1]
        for row in rows:
            code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
            self.assertEqual(code, 0, result)
        code, result = self.cli('action', '--id', rows[-1]['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_restore_preserves_unrelated_external_values(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        external = self.values()
        external['unrelated'] = 'externally edited'
        (self.home / 'compositor.json').write_text(json.dumps(external))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), dict(self.original, unrelated='externally edited'))

    def test_oversized_data_read_is_bounded(self):
        path = self.home / 'large.json'
        path.write_bytes(b' ' * 65537)
        with self.assertRaises(ValueError):
            backend.bounded_json(path)

    def test_private_state_directory_rejects_world_writable_location(self):
        directory = self.home / 'state' / ('omarchy-' + backend.SLUG)
        directory.mkdir(parents=True)
        directory.chmod(0o777)
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertNotEqual(code, 0, 'unsafe permissions accepted')
        self.assertEqual(self.values(), self.original)

    def test_malformed_ipc_shapes_return_json_failure_without_trace(self):
        row = backend.load_rows()[0]
        for kind in ['version', 'option']:
            with self.subTest(kind=kind):
                code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                       extra={'FIXTURE_MALFORMED': kind})
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
                self.assertEqual(self.values(), self.original)

    def test_hung_ipc_times_out_without_mutation(self):
        import time
        start = time.monotonic()
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_HANG': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('timed out', result['message'])
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.values(), self.original)

    def test_flooded_ipc_is_bounded(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FLOOD': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('64 KiB', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_symlink_snapshot_never_follows_arbitrary_file(self):
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        moved = self.home / 'saved.json'
        path.rename(moved)
        path.symlink_to(moved)
        before = self.values()
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertEqual(self.values(), before)

    def test_sandbox_is_not_connected_to_live_session(self):
        import os
        self.assertFalse(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'))
        self.assertFalse(os.environ.get('WAYLAND_DISPLAY'))
        self.assertFalse(pathlib.Path('/run/user').exists())
        self.assertFalse(pathlib.Path('/srv/projects').exists())
        devices = pathlib.Path('/proc/net/dev').read_text()
        self.assertNotIn('eth0', devices)
        self.assertNotIn('wlan0', devices)

    def test_persistence_failure_after_mutation_rolls_back(self):
        import os
        from unittest.mock import patch
        real_save = backend.save
        count = [0]
        def interrupted(directory, record):
            count[0] += 1
            if count[0] == 2:
                raise OSError('simulated fsync failure')
            real_save(directory, record)
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'save', interrupted):
            with self.assertRaisesRegex(ValueError, 'rollback confirmed'):
                backend.action(backend.load_rows()[0]['id'], 'apply')
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def test_after_replace_failure_partial_rollback_remains_recoverable(self):
        import json, os
        from unittest.mock import patch
        real_save, real_write = backend.save, backend.write_value
        saves, writes = [0], [0]
        def save(directory, record):
            saves[0] += 1
            real_save(directory, record)
            if saves[0] == 2:
                raise OSError('active save failed after replace')
        def write(key, value, expected):
            writes[0] += 1
            if writes[0] == 8:
                raise ValueError('IPC failed after first compensation')
            return real_write(key, value, expected)
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'save', save), patch.object(backend, 'write_value', write):
            with self.assertRaisesRegex(ValueError, 'retained'):
                backend.action('efficiency', 'apply')
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        self.assertEqual(writes[0], 8)
        self.assertEqual(record['phase'], 'pending')
        self.assertNotEqual({k:self.values()[k] for k in backend.SCHEMA}, record['expected'])
        code, result = self.cli('action', '--id', 'efficiency', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(path.exists())

    def test_group_kill_mid_compensation_recovers_before_and_after_replace(self):
        import json, os, signal, subprocess, time
        for stage, prior in [('before', 'first'), ('after', 'first'), ('before', 'prior'), ('after', 'prior')]:
            with self.subTest(stage=stage, prior=prior):
                marker = self.home / 'rollback-paused.json'; marker.unlink(missing_ok=True)
                caller = subprocess.Popen(['/usr/bin/python3', str(ROOT / 'tests/rollback_caller_fixture.py'), stage, prior],
                    env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    deadline = time.monotonic() + 6
                    while not marker.exists() and caller.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists(), 'caller did not reach compensating setter')
                    evidence = json.loads(marker.read_text())
                    self.assertEqual(evidence['pid'], caller.pid)
                    self.assertEqual(evidence['pgid'], caller.pid)
                    os.killpg(caller.pid, signal.SIGKILL)
                    out, err = caller.communicate(timeout=2)
                    self.assertEqual(caller.returncode, -signal.SIGKILL)
                    self.assertEqual((out, err), (b'', b''))
                    path = next((self.home / 'state').rglob('transaction.json'))
                    record = json.loads(path.read_text())
                    self.assertEqual(record, evidence['journal'])
                    self.assertEqual(record['phase'], 'pending')
                    self.assertEqual(record['before'], {k:self.original[k] for k in backend.SCHEMA})
                    mixed = {k:self.values()[k] for k in backend.SCHEMA}
                    self.assertNotEqual(mixed, record['previous'])
                    self.assertNotEqual(mixed, record['expected'])
                    # A truly external value must still block recovery without changing the receipt.
                    edited = self.values(); edited['general.border_size'] = 99
                    (self.home / 'compositor.json').write_text(json.dumps(edited))
                    receipt = path.read_bytes()
                    code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                    self.assertNotEqual(code, 0)
                    self.assertIn('conflict', result['message'].lower())
                    self.assertEqual(self.values(), edited)
                    self.assertEqual(path.read_bytes(), receipt)
                    (self.home / 'compositor.json').write_text(json.dumps(dict(edited, **mixed)))
                    code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                    self.assertEqual(code, 0, result)
                    self.assertEqual(self.values(), self.original)
                    self.assertFalse(path.exists())
                    print('FIXTURE_EVIDENCE ' + json.dumps({'stage': stage, 'prior': prior,
                        'caller_exit': caller.returncode, 'phase': record['phase'],
                        'external_edit_refused': True, 'baseline_restored': True}), flush=True)
                finally:
                    if caller.poll() is None:
                        os.killpg(caller.pid, signal.SIGKILL); caller.wait(timeout=2)
                    caller.stdout.close(); caller.stderr.close()

    def test_failed_rollback_intent_save_prevents_compensating_writes(self):
        import json, os
        from unittest.mock import patch
        real_save = backend.save
        saves = [0]
        def save(directory, record):
            saves[0] += 1
            if saves[0] == 2:
                real_save(directory, record)
                raise OSError('active save failed after replace')
            if saves[0] == 3:
                raise OSError('cannot persist compensation intent')
            return real_save(directory, record)
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'save', save):
            with self.assertRaisesRegex(ValueError, 'retained'):
                backend.action('efficiency', 'apply')
        self.assertEqual(saves[0], 3)
        self.assertEqual(int((self.home / 'eval-count').read_text()), 6)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        self.assertEqual(record['phase'], 'active')
        self.assertEqual({k:self.values()[k] for k in backend.SCHEMA}, record['expected'])
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_failed_restore_of_pending_mixture_compensates_to_actual_previous(self):
        import json
        self.assertEqual(self.cli('action', '--id', 'efficiency', '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text()); record['phase'] = 'pending'
        record['previous'] = dict(record['before']); path.write_text(json.dumps(record))
        mixed = self.values(); mixed['decoration.shadow.enabled'] = self.original['decoration.shadow.enabled']
        (self.home / 'compositor.json').write_text(json.dumps(mixed))
        (self.home / 'eval-count').unlink()
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply',
            extra={'FIXTURE_FAIL_AT': '2', 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('rollback confirmed', result['message'])
        self.assertEqual(self.values(), mixed)
        self.assertEqual(json.loads(path.read_text()), record)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_profiles_never_reenable_disabled_motion(self):
        import json
        self.original['animations.enabled'] = False
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        rows = backend.load_rows() if backend.SLUG != 'shader-deck' else backend.load_rows()[:1]
        for row in rows:
            code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
            self.assertEqual(code, 0, result)
            self.assertIs(self.values()['animations.enabled'], False)
        self.assertEqual(self.cli('action', '--id', rows[0]['id'], '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_child_closing_stdout_then_hanging_is_plain_timeout(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action','--id',row['id'],'--verb','apply','--apply',
                                extra={'FIXTURE_CLOSE_STDOUT':'1'})
        self.assertNotEqual(code,0)
        self.assertIn('timed out',result['message'])
        self.assertEqual(self.values(),self.original)

    def test_strict_data_validation_and_no_code_fields(self):
        self.assertTrue(callable(getattr(backend, "validate_rows", None)), "strict validation missing")
        rows = backend.load_rows()
        self.assertEqual(backend.validate_rows(rows), rows)
        import copy
        for value in [None, [], rows * 100, [dict(rows[0], code="os.execute('bad')")],
                      [rows[0], rows[0]], [dict(rows[0], id="../bad")],
                      [dict(rows[0], label="X" * 129)],
                      [dict(rows[0], settings={"exec": "bad"})]]:
            with self.subTest(value=str(value)[:80]):
                with self.assertRaises(ValueError):
                    backend.validate_rows(value)
        row = copy.deepcopy(rows[0])
        key = next(iter(row["settings"]))
        row["settings"][key] = "hl.dispatch('exit')"
        with self.assertRaises(ValueError):
            backend.validate_rows([row])

    def test_cli_refuses_action_without_explicit_apply(self):
        import subprocess, json
        p = subprocess.run(["/usr/bin/python3", str(RUNTIME / "backend.py"),
                            "action", "--id", "bad", "--verb", "apply"], capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0, "action lacks explicit apply guard")
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_catalog_is_bounded_and_has_unique_known_rows(self):
        self.assertTrue(callable(getattr(backend, "catalog", None)), "catalog behavior is missing")
        result = backend.catalog()
        self.assertEqual(result["actions"], ["apply", "restore", "favorite", "capture", "import", "export-preset", "compare"])
        self.assertEqual(result["actionLabel"], "Apply")
        rows = result["rows"]
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(all({"id", "label", "detail"} <= set(r) <= {"id", "label", "detail", "favorite", "preview"} for r in rows))
        self.assertTrue(all(type(r["favorite"]) is bool for r in rows))

if __name__ == "__main__":
    unittest.main()
