"""v0.3.0 behavioral slices, exercised only by the offline runner."""
import json
import os
import pathlib
import unittest
from unittest.mock import patch
import test_backend as base

backend = base.backend
RUNTIME = base.RUNTIME


class AdvancedTests(unittest.TestCase):
    home: pathlib.Path
    env: dict[str, str]
    setUp = base.BackendTests.setUp
    cli = base.BackendTests.cli
    values = base.BackendTests.values

    def test_every_runtime_and_test_python_source_compiles_without_bytecode_writes(self):
        files=[*RUNTIME.rglob('*.py'),*(base.ROOT/'tests').glob('*.py')]
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path.name):
                compile(path.read_bytes(),str(path),'exec')

    def test_recent_storage_failure_does_not_fabricate_apply_failure(self):
        ident=backend.load_rows()[0]['id']
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend.preferences,'remember',side_effect=OSError('fixture write refusal')):
            result=backend.action(ident,'apply')
        self.assertTrue(result['ok'])
        self.assertIn('warning',result['message'].lower())
        self.assertNotEqual(self.values(),self.original)
        self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_large_valid_preferences_cannot_overflow_catalog_or_hide_confirmed_action(self):
        ids=[str(i).zfill(3)+'x'*200 for i in range(512)]
        with patch.dict(os.environ,self.env,clear=True):
            prefs=backend.preferences.change(backend.SLUG,backend.PREFERENCE_SCHEMA,{})
        prefs['collections']={'group-'+str(i):ids for i in range(16)}
        # Seed a validated legacy store; normal new writes correctly reject this size.
        path=self.home/'.config/omarchy/lego'/backend.SLUG/'preferences.json'
        path.write_text(json.dumps(prefs))
        self.assertGreater(path.stat().st_size,1048576)
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(backend.preferences.read(backend.SLUG,backend.PREFERENCE_SCHEMA),prefs)
        code,result=self.cli('catalog')
        self.assertNotEqual(code,0)
        self.assertFalse(result['ok'])
        self.assertIn('limit',result['message'].lower())
        ident=backend.load_rows()[0]['id']
        code,result=self.cli('action','--id',ident,'--verb','apply','--apply')
        self.assertEqual(code,0,result)
        self.assertTrue(result['ok'])
        self.assertIn('warning',result['message'].lower())
        self.assertNotEqual(self.values(),self.original)
        self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_hardlinked_custom_store_is_rejected_without_modifying_other_link(self):
        code, result = self.cli('action', '--id', 'capture:current', '--verb', 'capture', '--apply', '--payload', '{"name":"Owned"}')
        self.assertEqual(code, 0, result)
        path = next((self.home / '.config').rglob('custom-presets.json'))
        other = self.home / 'other.json'
        os.link(path, other)
        saved = other.read_bytes()
        code, result = self.cli('catalog')
        self.assertNotEqual(code, 0)
        self.assertFalse(result['ok'])
        self.assertEqual(other.read_bytes(), saved)
        self.assertEqual(path.read_bytes(), saved)

    def test_json_file_reads_reject_symlinks_duplicates_and_special_files(self):
        data = self.home / 'source.json'
        data.write_text('{"valid":true}')
        link = self.home / 'link.json'
        link.symlink_to(data)
        with self.assertRaises(ValueError):
            backend.bounded_json(link)
        data.write_text('{"key":1,"key":2}')
        with self.assertRaises(ValueError):
            backend.bounded_json(data)
        fifo = self.home / 'pipe.json'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            backend.bounded_json(fifo)
        self.assertTrue(link.is_symlink())
        self.assertEqual(data.read_text(), '{"key":1,"key":2}')

    def test_unexpected_cli_options_fail_as_json_without_side_effects(self):
        for args in [('catalog', '--bogus'), ('catalog', '--payload', '{}'),
                     ('catalog', '--apply'), ('preferences', '--id', 'unknown'),
                     ('preferences', '--payload', '{"options":{}}'),
                     ('preferences', '--apply', '--payload', '{"recent":[]}')]:
            with self.subTest(args=args):
                code, result = self.cli(*args)
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / '.config').exists())

    def test_compare_reports_actual_typed_diffs_without_snapshot_or_setter(self):
        code, result = self.cli('action', '--id', 'spacious', '--verb', 'compare', '--apply')
        self.assertEqual(code, 0, result)
        row = next(r for r in backend.load_rows() if r['id']=='spacious')
        expected = [{'key':k, 'before':self.original[k], 'after':v} for k,v in row['settings'].items()
                    if self.original[k] != v]
        self.assertEqual(result['diff'], expected)
        self.assertIn('general.gaps_in', result['detail'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / 'eval-count').exists())
        self.assertIn('gaps_in', self.cli('catalog')[1]['rows'][0]['detail'])
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"showDiffs":false}}')[0], 0)
        self.assertNotIn('gaps_in', self.cli('catalog')[1]['rows'][0]['detail'])

    def test_preferences_catalog_favorite_recent_and_reset_preserve_custom_presets(self):
        code, result = self.cli('preferences')
        self.assertEqual(code, 0, result)
        self.assertIn('settingsSchema', result)
        self.assertEqual(result['preferences']['version'], 1)
        self.assertFalse((self.home / '.config').exists())
        code, result = self.cli('preferences', '--apply', '--payload', '{"options":{"showDiffs":false}}')
        self.assertEqual(code, 0, result)
        self.assertIs(result['preferences']['options']['showDiffs'], False)
        self.assertEqual(self.cli('action', '--id', 'compact-coding', '--verb', 'favorite', '--apply')[0], 0)
        code, listing = self.cli('catalog')
        self.assertEqual(code, 0, listing)
        self.assertEqual(listing['settingsSchema'], backend.PREFERENCE_SCHEMA)
        self.assertTrue(next(r for r in listing['rows'] if r['id']=='compact-coding')['favorite'])
        self.assertEqual(self.cli('action', '--id', 'capture:current', '--verb', 'capture', '--apply', '--payload', '{"name":"Keep this"}')[0], 0)
        self.assertEqual(self.cli('action', '--id', 'compact-coding', '--verb', 'apply', '--apply')[0], 0)
        receipt = next((self.home / 'state').rglob('transaction.json'))
        saved = receipt.read_bytes()
        self.assertEqual(self.cli('preferences')[1]['preferences']['recent'][0], 'compact-coding')
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"reset":true}')[0], 0)
        self.assertEqual(receipt.read_bytes(), saved)
        self.assertTrue(any(r['label']=='Keep this' for r in self.cli('catalog')[1]['rows']))
        self.assertEqual(self.cli('preferences')[1]['preferences']['favorites'], [])
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)

    def test_payload_parser_rejects_duplicate_nonfinite_deep_and_byte_overflow(self):
        for raw in ['{"name":"a","name":"b"}', '{"x":NaN}', '{"x":Infinity}',
                    '{"x":' + '['*100 + '0' + ']'*100 + '}', '[]',
                    json.dumps({'name':'😀'*4097}, ensure_ascii=False)]:
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(ValueError):
                    backend.parse_payload(raw)
        self.assertEqual(backend.parse_payload('{"name":"valid"}'), {'name':'valid'})

    def test_strict_import_roundtrip_is_inert_until_explicit_apply(self):
        row = next(r for r in backend.load_rows() if r['id'] == 'spacious')
        code, exported = self.cli('action', '--id', row['id'], '--verb', 'export-preset', '--apply')
        self.assertEqual(code, 0, exported)
        preset = dict(exported['preset'], name='Imported spacious')
        code, imported = self.cli('action', '--id', 'import:preset', '--verb', 'import', '--apply',
                                  '--payload', json.dumps(preset))
        self.assertEqual(code, 0, imported)
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'calls.jsonl').exists())
        code, applied = self.cli('action', '--id', imported['id'], '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, applied)
        for key, value in preset['settings'].items():
            self.assertEqual(self.values()[key], value)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        code, exported_again = self.cli('action', '--id', imported['id'], '--verb', 'export-preset', '--apply')
        self.assertEqual(code, 0, exported_again)
        self.assertEqual(exported_again['preset'], preset)

    def test_named_capture_survives_restart_and_exports_actual_values(self):
        code, result = self.cli('action', '--id', 'capture:current', '--verb', 'capture', '--apply',
                                '--payload', json.dumps({'name': 'My writing desk'}))
        self.assertEqual(code, 0, result)
        ident = result['id']
        self.assertTrue(ident.startswith('custom-'))
        code, listing = self.cli('catalog')
        self.assertEqual(code, 0, listing)
        self.assertIn(ident, [r['id'] for r in listing['rows']])
        code, result = self.cli('action', '--id', ident, '--verb', 'export-preset', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['preset'], {'version': 1, 'slug': backend.SLUG,
                         'name': 'My writing desk', 'settings': {k:self.original[k] for k in backend.SCHEMA}})
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'eval-count').exists())
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def test_five_appearance_modes_have_distinct_complete_allowlisted_values(self):
        rows = {row['id']: row for row in backend.load_rows()}
        modes = {'compact-coding', 'focused-writing', 'spacious', 'presentation', 'low-effects'}
        self.assertTrue(modes <= rows.keys(), modes - rows.keys())
        settings = [rows[key]['settings'] for key in sorted(modes)]
        self.assertEqual(len({json.dumps(s, sort_keys=True) for s in settings}), 5)
        for values in settings:
            self.assertEqual(set(values), set(backend.SCHEMA))
            self.assertFalse(set(values) & {'exec', 'workspace', 'monitor'})
