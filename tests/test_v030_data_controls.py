"""Trust-boundary controls for existing v0.3.0 capture/import/preference guards."""
import copy
import json
import os
import pathlib
import random
import unittest
from unittest.mock import patch
import test_backend as base
backend=base.backend

class DataControls(unittest.TestCase):
    setUp=base.BackendTests.setUp
    cli=base.BackendTests.cli
    values=base.BackendTests.values

    def preset(self,name='Imported'):
        return {'version':1,'slug':backend.SLUG,'name':name,
                'settings':{k:self.original[k] for k in backend.SCHEMA}}

    def test_import_rejects_code_unknown_keys_bad_shapes_and_overflow_without_ipc(self):
        value=self.preset()
        invalid=[None,[],{},dict(value,version=True),dict(value,version=2),dict(value,slug='foreign'),
                 dict(value,code='hl.dispatch("exit")'),dict(value,output='/other'),
                 dict(value,name=''),dict(value,name=' '+value['name']),dict(value,name='X'*81),
                 dict(value,name='a\nb'),dict(value,settings={}),dict(value,settings={'exec':'bad'})]
        key=next(iter(backend.SCHEMA))
        for bad in ['os.execute("bad")',None,{},['bad'],3.5]:
            changed=copy.deepcopy(value);changed['settings'][key]=bad;invalid.append(changed)
        raw=[json.dumps(v) for v in invalid]+['{"name":"a","name":"b"}','{"value":NaN}',
             json.dumps(dict(value,name='😀'*5000),ensure_ascii=False)]
        for payload in raw:
            with self.subTest(payload=payload[:80]):
                code,result=self.cli('action','--id','import:preset','--verb','import','--apply','--payload',payload)
                self.assertNotEqual(code,0,result)
                self.assertFalse(result['ok'])
        self.assertFalse((self.home/'calls.jsonl').exists())
        self.assertFalse((self.home/'.config').exists())
        self.assertEqual(self.values(),self.original)

    def test_custom_store_duplicate_limit_corruption_and_symlink_fail_closed(self):
        value=self.preset('Existing')
        self.assertEqual(self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(value))[0],0)
        path=next((self.home/'.config').rglob('custom-presets.json'))
        saved=path.read_bytes()
        code,result=self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(value))
        self.assertNotEqual(code,0)
        self.assertEqual(path.read_bytes(),saved)
        with patch.dict(os.environ,self.env,clear=True):
            backend.save_custom(path.parent,[dict(value,name='entry-'+str(i)) for i in range(32)])
        saved=path.read_bytes()
        self.assertNotEqual(self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(value))[0],0)
        self.assertEqual(path.read_bytes(),saved)
        path.write_bytes(b'not JSON')
        self.assertNotEqual(self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(value))[0],0)
        self.assertEqual(path.read_bytes(),b'not JSON')
        path.unlink();other=self.home/'other.json';other.write_bytes(saved);other.chmod(0o600);path.symlink_to(other)
        self.assertNotEqual(self.cli('catalog')[0],0)
        self.assertEqual(other.read_bytes(),saved)
        self.assertTrue(path.is_symlink())

    def test_custom_ancestor_symlink_cannot_redirect_import(self):
        elsewhere=self.home/'elsewhere';elsewhere.mkdir()
        (self.home/'.config').symlink_to(elsewhere)
        code,result=self.cli('action','--id','import:preset','--verb','import','--apply','--payload',json.dumps(self.preset()))
        self.assertNotEqual(code,0)
        self.assertEqual(list(elsewhere.iterdir()),[])
        self.assertFalse((self.home/'calls.jsonl').exists())

    def test_preferences_cannot_authorize_unknown_membership_or_overwrite_corruption(self):
        code,result=self.cli('preferences','--apply','--payload','{"favorites":["not-a-row"]}')
        self.assertEqual(code,0,result)
        self.assertNotEqual(self.cli('action','--id','not-a-row','--verb','favorite','--apply')[0],0)
        path=next((self.home/'.config').rglob('preferences.json'))
        saved=path.read_bytes()
        for payload in ['{"version":1}','{"recent":[]}','{"reset":true,"favorites":[]}',
                        '{"options":{"unknown":1}}','{"options":{"showDiffs":3}}']:
            self.assertNotEqual(self.cli('preferences','--apply','--payload',payload)[0],0)
            self.assertEqual(path.read_bytes(),saved)
        path.write_bytes(b'broken')
        self.assertNotEqual(self.cli('preferences','--apply','--payload','{"reset":true}')[0],0)
        self.assertEqual(path.read_bytes(),b'broken')
        self.assertFalse((self.home/'calls.jsonl').exists())

    def test_seeded_allowlist_matches_independent_type_and_bound_oracle(self):
        rng=random.Random(3030)
        samples=[None,True,False,'false','hl.config({})',[],{},-1,0,1,100,101,10000,10001,1.5]
        for _ in range(20000):
            key=rng.choice(list(backend.SCHEMA))
            kind=backend.SCHEMA[key]
            value=rng.choice(samples) if rng.randrange(2) else [rng.choice(samples) for _ in range(rng.randrange(6))]
            if kind=='bool':expected=type(value) is bool
            elif kind=='int':expected=type(value) is int and 0<=value<=100
            else:expected=type(value) is list and len(value)==4 and all(type(v) is int and 0<=v<=10000 for v in value)
            self.assertEqual(backend.valid_value(key,value),expected,(key,value))
