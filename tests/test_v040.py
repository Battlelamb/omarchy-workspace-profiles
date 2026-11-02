"""Scoped appearance actions against observable fake IPC; never session management."""
import json
import os
import pathlib
import unittest
from unittest.mock import patch
import test_backend as base
backend=base.backend
SPACING={'general.gaps_in','general.gaps_out','general.border_size'}
EFFECTS={'decoration.rounding','decoration.blur.enabled','decoration.shadow.enabled'}


class ScopeTests(unittest.TestCase):
    home: pathlib.Path
    env: dict
    original: dict
    setUp=base.BackendTests.setUp
    cli=base.BackendTests.cli
    values=base.BackendTests.values

    def scope(self,value):
        code,result=self.cli('preferences','--apply','--payload',json.dumps({'options':{'applyScope':value}}))
        self.assertEqual(code,0,result)

    def test_scope_compare_apply_and_restore_match_exact_admitted_keys(self):
        initial=self.cli('preferences')[1]
        self.assertIn('applyScope',initial['settingsSchema'])
        self.assertEqual(initial['preferences']['options']['applyScope'],'all')
        row=next(r for r in backend.load_rows() if r['id']=='compact-coding')
        for scope,keys in [('all',SPACING|EFFECTS),('spacing-only',SPACING),('effects-only',EFFECTS)]:
            with self.subTest(scope=scope):
                self.scope(scope)
                before=self.values()
                count=(self.home/'eval-count').read_bytes() if (self.home/'eval-count').exists() else None
                code,result=self.cli('action','--id',row['id'],'--verb','compare','--apply')
                self.assertEqual(code,0,result)
                self.assertEqual({d['key'] for d in result['diff']},keys)
                self.assertEqual(self.values(),before)
                self.assertFalse(list((self.home/'state').rglob('transaction.json')))
                if count is not None:self.assertEqual((self.home/'eval-count').read_bytes(),count)
                with patch.dict(os.environ,self.env,clear=True),patch.object(backend,'write_value',wraps=backend.write_value) as setter:
                    self.assertTrue(backend.action(row['id'],'apply')['ok'])
                    self.assertEqual({call.args[0] for call in setter.call_args_list},keys)
                expected=dict(self.original,**{k:row['settings'][k] for k in keys})
                self.assertEqual(self.values(),expected)
                self.scope('effects-only' if scope!='effects-only' else 'spacing-only')
                self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
                self.assertEqual(self.values(),self.original)

    def test_scope_switch_keeps_first_baseline_and_full_external_edit_guards(self):
        self.scope('spacing-only')
        self.assertEqual(self.cli('action','--id','compact-coding','--verb','apply','--apply')[0],0)
        path=next((self.home/'state').rglob('transaction.json'))
        baseline=json.loads(path.read_text())['before']
        self.scope('effects-only')
        self.assertEqual(self.cli('action','--id','presentation','--verb','apply','--apply')[0],0)
        self.assertEqual(json.loads(path.read_text())['before'],baseline)
        self.assertEqual(baseline,{k:self.original[k] for k in backend.SCHEMA})
        # Even an edit outside today's scope remains protected by the full receipt.
        edited=self.values()
        edited['general.gaps_in']=[99]*4
        (self.home/'compositor.json').write_text(json.dumps(edited))
        saved,count=path.read_bytes(),(self.home/'eval-count').read_bytes()
        for ident,verb in [('comfortable','apply'),('restore:last','restore')]:
            code,result=self.cli('action','--id',ident,'--verb',verb,'--apply')
            self.assertNotEqual(code,0,result)
            self.assertIn('conflict',result['message'].lower())
            self.assertEqual(self.values(),edited)
            self.assertEqual(path.read_bytes(),saved)
            self.assertEqual((self.home/'eval-count').read_bytes(),count)
        expected=json.loads(saved)['expected']
        (self.home/'compositor.json').write_text(json.dumps(dict(edited,**expected)))
        self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_scoped_partial_setter_failure_compensates_only_scope_exactly(self):
        for scope,keys in [('spacing-only',SPACING),('effects-only',EFFECTS)]:
            for after in (False,True):
                with self.subTest(scope=scope,lost_ack=after):
                    self.setUp()
                    self.scope(scope)
                    with patch.dict(os.environ,dict(self.env,FIXTURE_FAIL_AT='2',**({'FIXTURE_FAIL_AFTER':'1'} if after else {})),clear=True),patch.object(backend,'write_value',wraps=backend.write_value) as setter:
                        with self.assertRaisesRegex(ValueError,'rollback confirmed'):
                            backend.action('compact-coding','apply')
                        self.assertTrue(setter.call_count>=3)
                        self.assertTrue({call.args[0] for call in setter.call_args_list}<=keys)
                    self.assertEqual(self.values(),self.original)
                    self.assertFalse(list((self.home/'state').rglob('transaction.json')))

    def test_scope_does_not_truncate_capture_export_or_relax_import_validation(self):
        self.scope('spacing-only')
        code,result=self.cli('action','--id','capture:current','--verb','capture','--apply','--payload','{"name":"Full capture"}')
        self.assertEqual(code,0,result)
        code,exported=self.cli('action','--id',result['id'],'--verb','export-preset','--apply')
        self.assertEqual(code,0,exported)
        self.assertEqual(exported['preset']['settings'],{k:self.original[k] for k in backend.SCHEMA})
        incomplete=dict(exported['preset'],name='Incomplete',settings={'general.gaps_in':[1]*4})
        self.assertNotEqual(self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(incomplete))[0],0)
        self.assertEqual(self.values(),self.original)
        self.assertFalse((self.home/'eval-count').exists())
        self.assertFalse((self.home/'state').exists())

    def test_invalid_scope_options_are_atomic_and_configuration_calls_no_ipc(self):
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend,'run_hypr',side_effect=AssertionError('configuration must not call IPC')):
            backend.preference_command({'options':{'applyScope':'spacing-only'}},True)
            path=self.home/'.config/omarchy/lego/workspace-profiles/preferences.json'
            saved=path.read_bytes()
            for value in [True,0,None,[],{},'spacing','spacing-only\n']:
                with self.assertRaises(ValueError):
                    backend.preference_command({'options':{'applyScope':value}},True)
                self.assertEqual(path.read_bytes(),saved)
            backend.preference_command({'reset':True},True)
            self.assertEqual(backend.catalog()['preferences']['options']['applyScope'],'all')
        self.assertFalse((self.home/'calls.jsonl').exists())
