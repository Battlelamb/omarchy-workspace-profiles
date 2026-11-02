#!/usr/bin/python3
"""Pause a real caller after one compensating setter for sandbox group SIGKILL."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend', root / Path(json.loads((root / 'manifest.json').read_text())['entryPoints']['overlay']).parent / 'backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
home = Path.home()
stage, prior = sys.argv[1:]
if prior == 'prior':
    backend.action('comfortable', 'apply')
real_save, real_write = backend.save, backend.write_value
compensating = False

def save(directory, record):
    global compensating
    if record['phase'] == 'active' and not compensating:
        if stage == 'after':
            real_save(directory, record)
        compensating = True
        raise OSError('active publication fault ' + stage + ' replace')
    return real_save(directory, record)

def write(key, value, expected):
    result = real_write(key, value, expected)
    if compensating:
        recordfile = next((home / 'state').rglob('transaction.json'))
        marker = home / '.rollback-paused.json'
        marker.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp(),
            'key': key, 'journal': json.loads(recordfile.read_text())}))
        marker.replace(home / 'rollback-paused.json')
        while True:
            time.sleep(0.1)
    return result

backend.save, backend.write_value = save, write
backend.action('efficiency', 'apply')
raise SystemExit('compensation boundary not reached')
