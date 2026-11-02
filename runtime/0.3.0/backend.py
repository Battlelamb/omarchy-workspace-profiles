#!/usr/bin/python3
"""Constrained runtime presets. No startup config changes. GPL-3.0-only."""
import argparse
import json
import re
import sys
from pathlib import Path

SLUG = 'workspace-profiles'
DATA = Path(__file__).resolve().parent / 'data'
SCHEMAS = {
    'motion-presets': {'animations.enabled': 'bool', 'animations.workspace_wraparound': 'bool'},
    'workspace-profiles': {'general.gaps_in': 'gap', 'general.gaps_out': 'gap',
        'general.border_size': 'int', 'decoration.rounding': 'int',
        'decoration.blur.enabled': 'bool', 'decoration.shadow.enabled': 'bool'},
    'shader-deck': {'decoration.screen_shader': 'shader'},
}
SCHEMA = SCHEMAS[SLUG] if SLUG != 'TEMPLATE' else {}
PREFERENCE_SCHEMA = {'showDiffs': {'type': 'boolean', 'default': True, 'label': 'Show appearance value summaries'}}
sys.path.insert(0, str(Path(__file__).resolve().parent))
import preferences


def bounded_json(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError('Cannot safely open bounded JSON file') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('JSON input must be a regular file')
        if info.st_size > 65536:
            raise ValueError('Data exceeds 64 KiB limit')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Data exceeds 64 KiB limit')
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('JSON input changed while reading')
        return strict_json(raw)
    finally:
        os.close(fd)


def valid_value(key, value, preset=False):
    kind = SCHEMA.get(key)
    if kind == 'bool':
        return type(value) is bool
    if kind == 'int':
        return type(value) is int and 0 <= value <= 100
    if kind == 'gap':
        return (type(value) is list and len(value) == 4
                and all(type(v) is int and 0 <= v <= 10000 for v in value))
    if kind == 'shader':
        if preset:
            return value in ('', '@grayscale.frag', '@warm.frag')
        return (type(value) is str and len(value) <= 4096
                and not any(ord(c) < 32 or ord(c) == 127 for c in value)
                and (value == '' or value.startswith('/')))
    return False


def validate_rows(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise ValueError('Expected 1–64 known preset rows')
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'id', 'label', 'detail', 'settings'}:
            raise ValueError('Preset fields must be id, label, detail, settings only')
        for key, maximum in [('id', 64), ('label', 128), ('detail', 512)]:
            value = row[key]
            if type(value) is not str or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
                raise ValueError('Invalid preset text')
        if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate preset ID')
        seen.add(row['id'])
        values = row['settings']
        if type(values) is not dict or not values or not set(values) <= set(SCHEMA):
            raise ValueError('Unsupported preset settings')
        if any(not valid_value(k, v, True) for k, v in values.items()):
            raise ValueError('Invalid preset setting value')
        if SLUG == 'motion-presets' and values.get('animations.enabled') is True:
            raise ValueError('Motion presets cannot enable previously disabled animations')
    return rows


def load_rows():
    rows = validate_rows(bounded_json(DATA / 'presets.json'))
    return rows + [custom_row(preset) for preset in load_custom()]


def catalog():
    prefs = preferences.read(SLUG, PREFERENCE_SCHEMA)
    rows = []
    for row in load_rows():
        item = {k: row[k] for k in ('id', 'label', 'detail')}
        item['favorite'] = row['id'] in prefs['favorites']
        if prefs['options']['showDiffs']:
            item['detail'] += ' Values: ' + '; '.join(k + '=' + json.dumps(v) for k,v in row['settings'].items())
        rows.append(item)
    return {'rows': rows,
            'preferences': prefs, 'settingsSchema': PREFERENCE_SCHEMA,
            'actions': ['apply', 'restore', 'favorite', 'capture', 'import', 'export-preset', 'compare'], 'actionLabel': 'Apply',
            'message': 'Explicit runtime Apply only; Restore preserves prior values. Not enabled at startup.'}


class BackendParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid command or options; see --help')


def main():
    parser = BackendParser(allow_abbrev=False)
    parser.add_argument('command', choices=['catalog', 'action', 'preferences'])
    parser.add_argument('--id', default='')
    parser.add_argument('--verb', default='')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--payload')
    try:
        args = parser.parse_args()
        if args.command == 'preferences':
            if args.id or args.verb:
                raise ValueError('Preferences accepts no selection or verb')
            payload = parse_payload(args.payload) if args.payload is not None else None
            result = preference_command(payload, args.apply)
        elif args.command == 'catalog':
            if args.payload is not None or args.apply or args.id or args.verb:
                raise ValueError('Catalog accepts no action options')
            result = catalog()
        else:
            if not args.apply:
                raise ValueError('Action requires explicit --apply')
            payload = parse_payload(args.payload) if args.payload is not None else None
            if args.verb in ('capture', 'import', 'export-preset'):
                result = custom_action(args.id, args.verb, payload)
            else:
                if payload is not None:
                    raise ValueError('This action accepts no payload')
                result = action(args.id, args.verb)
        encoded = json.dumps(result, ensure_ascii=True)
        if len(encoded.encode('utf-8')) >= 1048576:
            if args.command == 'action' and result.get('ok') is True:
                result.pop('preferences', None)
                result['message'] += ' Warning: preference snapshot omitted to respect the 1 MiB output limit; action remains confirmed.'
                encoded = json.dumps(result, ensure_ascii=True)
            else:
                raise ValueError('Preference snapshot exceeds 1 MiB output limit; Reset or repair local preferences')
        if len(encoded.encode('utf-8')) >= 1048576:
            raise ValueError('Result exceeds 1 MiB output limit')
        print(encoded)
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'message': str(error)[:300]}))
        return 1


# These helpers are copied locally into each independent plugin, not a runtime dependency.
import contextlib
import fcntl
import hashlib
import os
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time


def run_hypr(*args):
    tool = shutil.which('hyprctl')
    if not tool:
        raise ValueError('hyprctl is unavailable; install a compatible Omarchy session separately')
    p = subprocess.Popen([tool, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    collected = bytearray()
    deadline = time.monotonic() + 3
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('hyprctl timed out; snapshot retained for Restore')
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                    collected.extend(data)
                    if len(collected) > 65536:
                        raise ValueError('hyprctl output exceeded 64 KiB')
            p.wait(timeout=max(0.001, deadline - time.monotonic()))
        if p.returncode:
            raise ValueError('hyprctl failed; check compositor availability')
        return collected.decode('utf-8').strip()
    except subprocess.TimeoutExpired:
        raise ValueError('hyprctl timed out; snapshot retained for Restore') from None
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        p.stdout.close()


def session():
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not re.fullmatch('[a-zA-Z0-9_.-]{1,128}', instance):
        raise ValueError('No valid Hyprland session; open from your compositor session')
    info = json.loads(run_hypr('-j', 'version'))
    if type(info) is not dict or info.get('version') != '0.56.2':
        raise ValueError('Adapter requires qualified Hyprland Lua 0.56.2; other versions fail closed')
    return instance


def read_values():
    result = {}
    for key, kind in SCHEMA.items():
        row = json.loads(run_hypr('-j', 'getoption', key))
        if type(row) is not dict or row.get('option') != key:
            raise ValueError('Unexpected compositor option response')
        field = {'gap': 'css', 'shader': 'str'}.get(kind, kind)
        value = row.get(field)
        if kind == 'gap' and type(value) is str and re.fullmatch(r'\d+( \d+){3}', value):
            value = [int(x) for x in value.split()]
        if kind == 'shader' and value == '[[EMPTY]]':
            value = ''
        if not valid_value(key, value):
            raise ValueError('Unsupported stored compositor value; no mutation performed')
        result[key] = value
    return result


def lua_literal(value):
    if type(value) is bool:
        return str(value).lower()
    if type(value) is int:
        return str(value)
    if type(value) is list:
        return '{' + ','.join(k + '=' + str(v) for k, v in zip(('top','right','bottom','left'), value)) + '}'
    # Lua supports escaped UTF-8 bytes and decimal escapes, not JSON \u escapes.
    return '"' + ''.join('\\%03d' % b for b in value.encode('utf-8')) + '"'


def write_value(key, value, expected):
    if key not in SCHEMA or not valid_value(key, value):
        raise ValueError('Rejected unsupported compositor mutation')
    guards = []
    for name, old in expected.items():
        guards.append('local v=hl.get_config(' + lua_literal(name) + ');')
        if type(old) is list:
            check = 'type(v)=="table" and ' + ' and '.join('v.' + k + '==' + str(v) for k, v in zip(('top','right','bottom','left'), old))
        else:
            check = 'v==' + lua_literal(old)
        guards.append('assert(' + check + ',"Preset conflict: external edit");')
    code = ''.join(guards) + 'hl.config({[' + lua_literal(key) + ']=' + lua_literal(value) + '});'
    if run_hypr('eval', code) != 'ok':
        raise ValueError('Compositor rejected setting or detected an external edit')


def state_dir(instance):
    root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    if not root.is_absolute():
        raise ValueError('XDG_STATE_HOME must be absolute')
    root = root / ('omarchy-' + SLUG)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError('Unsafe preset state directory')
    directory = root / hashlib.sha256(instance.encode()).hexdigest()[:24]
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise ValueError('Unsafe session state directory')
    return directory


@contextlib.contextmanager
def locked(directory):
    fd = os.open(directory / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another preset action is in progress; retry') from None
        yield
    finally:
        os.close(fd)


def save(directory, record):
    fd, temporary = tempfile.mkstemp(prefix='.transaction-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'transaction.json')
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state(directory, instance):
    path = directory / 'transaction.json'
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('Unsafe snapshot symlink')
    record = bounded_json(path)
    if type(record) is not dict or record.get('instance') != instance:
        raise ValueError('Invalid session snapshot')
    if type(record.get('id')) is not str or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', record['id']):
        raise ValueError('Invalid snapshot preset ID')
    if record.get('phase') not in ('pending', 'active'):
        raise ValueError('Invalid snapshot phase')
    for field in ('before', 'expected', 'previous'):
        values = record.get(field)
        if type(values) is not dict or set(values) != set(SCHEMA) or any(not valid_value(k, v) for k, v in values.items()):
            raise ValueError('Invalid snapshot values')
    return record


def apply_transaction(directory, instance, row_id, current, target, old_record, restoring):
    record = {'instance': instance, 'id': row_id, 'phase': 'pending',
              'before': old_record['before'] if old_record else dict(current),
              'previous': dict(current), 'expected': dict(target)}
    save(directory, record)
    try:
        for key, value in target.items():
            if current[key] != value:
                write_value(key, value, current)
                current[key] = value
        if read_values() != target:
            raise ValueError('Compositor readback did not confirm settings')
        if restoring:
            (directory / 'transaction.json').unlink()
        else:
            save(directory, dict(record, phase='active', previous=dict(target)))
    except (ValueError, OSError, subprocess.SubprocessError) as failure:
        try:
            # Active publication may have succeeded before fsync failed; journal compensation first.
            save(directory, record)
            actual = read_values()
            previous = record['previous']
            # Restore only values this transaction could have written, never a divergent external value.
            for key in reversed(list(target)):
                if actual[key] != previous[key]:
                    if actual[key] != target[key]:
                        raise ValueError('External edit conflicts with rollback')
                    write_value(key, previous[key], actual)
                    actual[key] = previous[key]
            if read_values() != previous:
                raise ValueError('Rollback readback failed')
            if old_record:
                save(directory, old_record)
            else:
                (directory / 'transaction.json').unlink()
        except (ValueError, OSError, subprocess.SubprocessError):
            raise ValueError('Preset failed; rollback could not complete. Snapshot retained; resolve external edits and use Restore.') from None
        raise ValueError('Preset failed; rollback confirmed previous compositor values.') from failure


def action(row_id, verb):
    rows = {} if (row_id, verb) == ('restore:last', 'restore') else {r['id']: r for r in load_rows()}
    if verb == 'favorite' and row_id in rows:
        return {'ok': True, 'message': 'Favorite updated.', 'preferences': preferences.toggle(SLUG, PREFERENCE_SCHEMA, row_id)}
    if verb == 'compare' and row_id in rows:
        session()
        current = read_values()
        diff = [{'key': k, 'before': current[k], 'after': v} for k,v in rows[row_id]['settings'].items() if current[k] != v]
        return {'ok': True, 'message': 'Appearance diff only; no settings changed.', 'diff': diff,
                'detail': '\n'.join(d['key'] + ': ' + json.dumps(d['before']) + ' -> ' + json.dumps(d['after']) for d in diff) or 'No differences.'}
    if (row_id not in rows and (row_id, verb) != ('restore:last', 'restore')) or verb not in ('apply', 'restore'):
        raise ValueError('Unknown preset ID or action; refresh catalogue')
    instance = session()
    directory = state_dir(instance)
    with locked(directory):
        current = read_values()
        record = load_state(directory, instance)
        if record:
            if record['phase'] == 'pending':
                if verb != 'restore':
                    raise ValueError('Interrupted action; use Restore before applying another preset')
                acceptable = all(current[k] in (record['previous'][k], record['expected'][k]) for k in SCHEMA)
            else:
                acceptable = current == record['expected']
            if not acceptable:
                raise ValueError('External edit conflicts with snapshot; refusing to overwrite it')
        if verb == 'restore':
            if not record:
                raise ValueError('No snapshot for this session')
            if row_id == 'restore:last':
                row_id = record['id']
            target = record['before']
        else:
            target = dict(current)
            for key, value in rows[row_id]['settings'].items():
                if type(value) is str and value.startswith('@'):
                    raise ValueError('Shader watchdog is not ready; effect refused')
                target[key] = value
        apply_transaction(directory, instance, row_id, current, target, record, verb == 'restore')
        result = {'ok': True, 'message': 'Previous compositor values restored.' if verb == 'restore'
                  else 'Runtime preset applied and read back; Restore is available.'}
        return remember_result(result, row_id) if verb == 'apply' else result


def preference_command(payload, apply):
    if payload is None:
        if apply:
            raise ValueError('Preferences writes require a payload')
        prefs = preferences.read(SLUG, PREFERENCE_SCHEMA)
    else:
        if not apply:
            raise ValueError('Preferences writes require explicit --apply')
        if payload == {'reset': True} and type(payload.get('reset')) is bool:
            prefs = preferences.reset(SLUG, PREFERENCE_SCHEMA)
        else:
            current = preferences.read(SLUG, PREFERENCE_SCHEMA)
            if len(json.dumps(current, ensure_ascii=True).encode('utf-8')) > 900000:
                raise ValueError('Existing preferences exceed response limit; Reset or repair before updating')
            prefs = preferences.change(SLUG, PREFERENCE_SCHEMA, payload)
    return {'ok': True, 'message': 'Local preferences; no compositor setting changed.',
            'preferences': prefs, 'settingsSchema': PREFERENCE_SCHEMA}


def remember_result(result, row_id):
    try:
        result['preferences'] = preferences.remember(SLUG, PREFERENCE_SCHEMA, row_id)
    except (ValueError, OSError):
        result['message'] += ' Warning: recent selection could not be saved; external action remains confirmed.'
    return result


def parse_payload(raw):
    if len(raw.encode('utf-8')) > 16384:
        raise ValueError('Payload exceeds 16384 UTF-8 bytes')
    value = strict_json(raw)
    if type(value) is not dict:
        raise ValueError('Payload must be a JSON object')
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('Nonfinite JSON number')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (RecursionError, UnicodeError):
        raise ValueError('Invalid or deeply nested JSON') from None
    def check(item, depth=0):
        if depth > 12:
            raise ValueError('JSON nesting exceeds 12 levels')
        if type(item) is dict:
            for key, val in item.items():
                check(key, depth + 1)
                check(val, depth + 1)
        elif type(item) is list:
            for val in item:
                check(val, depth + 1)
        elif type(item) is float:
            import math
            if not math.isfinite(item):
                raise ValueError('Nonfinite JSON number')
        elif type(item) is str:
            try:
                item.encode('utf-8')
            except UnicodeError:
                raise ValueError('JSON contains invalid Unicode') from None
    check(value)
    return value


def custom_directory(create=False):
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    if not root.is_absolute():
        raise ValueError('XDG_CONFIG_HOME must be absolute')
    directory = root / 'omarchy/lego' / SLUG
    # Reject ancestor symlinks, including a redirected XDG root, before any access.
    for part in reversed([directory, *directory.parents]):
        if part.is_symlink():
            raise ValueError('Unsafe custom preset directory symlink')
        if part.exists() and not part.is_dir():
            raise ValueError('Custom preset ancestor is not a directory')
        if create and not part.exists():
            part.mkdir(mode=0o700)
    if directory.exists():
        info = directory.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Custom preset directory must be owned and private')
    return directory


def validate_custom(value):
    if (type(value) is not dict or set(value) != {'version', 'slug', 'name', 'settings'}
            or type(value['version']) is not int or value['version'] != 1 or value['slug'] != SLUG):
        raise ValueError('Expected version 1 preset for this plugin, with name and settings only')
    name = value['name']
    if (type(name) is not str or not 1 <= len(name) <= 80 or name != name.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError('Preset name must be 1–80 printable characters without edge spaces')
    settings = value['settings']
    if (type(settings) is not dict or set(settings) != set(SCHEMA)
            or any(not valid_value(k, v) for k, v in settings.items())):
        raise ValueError('Custom preset requires complete allowlisted typed settings')
    return value


def custom_row(value):
    return {'id': 'custom-' + hashlib.sha256(value['name'].encode()).hexdigest()[:16],
            'label': value['name'], 'detail': 'Saved local appearance; Apply is explicit.',
            'settings': value['settings']}


def load_custom():
    path = custom_directory() / 'custom-presets.json'
    if not path.exists() and not path.is_symlink():
        return []
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('Custom presets must be an owned private regular file')
    rows = bounded_json(path)
    if type(rows) is not list or len(rows) > 32:
        raise ValueError('At most 32 custom presets are allowed')
    rows = [validate_custom(row) for row in rows]
    if len({custom_row(row)['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate custom preset name')
    return rows


def save_custom(directory, rows):
    raw = json.dumps(rows, ensure_ascii=False).encode('utf-8')
    if len(raw) > 65536:
        raise ValueError('Custom presets exceed 64 KiB')
    fd, temporary = tempfile.mkstemp(prefix='.custom-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'custom-presets.json')
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def custom_action(row_id, verb, payload):
    if verb == 'export-preset':
        if payload is not None:
            raise ValueError('Export accepts no payload or output path')
        rows = {r['id']: r for r in load_rows()}
        if row_id not in rows:
            raise ValueError('Unknown preset ID; refresh catalogue')
        row = rows[row_id]
        value = validate_custom({'version': 1, 'slug': SLUG, 'name': row['label'], 'settings': row['settings']})
        return remember_result({'ok': True, 'message': 'Preset exported as inert JSON; no output file written.',
                'preset': value, 'detail': json.dumps(value, ensure_ascii=True)}, row_id)
    if verb == 'import' and row_id == 'import:preset':
        value = validate_custom(payload)
    elif verb == 'capture' and row_id == 'capture:current' and type(payload) is dict and set(payload) == {'name'}:
        value = validate_custom({'version': 1, 'slug': SLUG, 'name': payload['name'],
                                 'settings': {k: False if kind == 'bool' else ([0]*4 if kind == 'gap' else 0) for k, kind in SCHEMA.items()}})
        session()
        value['settings'] = read_values()
    else:
        raise ValueError('Capture requires capture:current and name; Import requires import:preset and preset JSON')
    directory = custom_directory(create=True)
    with locked(directory):
        rows = load_custom()
        if len(rows) == 32 or any(custom_row(r)['id'] == custom_row(value)['id'] for r in rows):
            raise ValueError('Preset name already exists or 32-preset limit reached; nothing overwritten')
        save_custom(directory, rows + [value])
        if value not in load_custom():
            raise ValueError('Custom preset readback failed')
    return {'ok': True, 'message': 'Preset saved locally; compositor values unchanged.', 'id': custom_row(value)['id']}


if __name__ == '__main__':
    sys.exit(main())
