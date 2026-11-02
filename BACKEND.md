# Backend operations and limits

## Contract and providers

System `/usr/bin/python3`, standard library, installed `hyprctl`, Hyprland Lua
**0.56.2** only. Other versions fail closed until separately qualified. Backend
and data resolve relative to `__file__`, not cwd; no plugin depends on another.
No installation, default enablement, autostart service or config include is added.
Catalogue is static and has no IPC/state writes; Apply verifies provider/version
and session. Missing providers/session and malformed responses fail with JSON.
No catalogue or selection performs an action.

```
/usr/bin/python3 runtime/0.2.1/backend.py catalog
/usr/bin/python3 runtime/0.2.1/backend.py action --id <known-id> --verb apply --apply
/usr/bin/python3 runtime/0.2.1/backend.py action --id restore:last --verb restore --apply
```

`--apply` is mandatory for every user action. Fresh full membership and strict
fields/types are checked, not a QML row or arbitrary command/path. Catalogue
returns one JSON object with bounded id/label/detail rows, Apply primary and
advertised Restore. Success means normal IPC acknowledgement plus value readback;
failures are nonzero JSON without a traceback. State is never trusted as Lua.

## Inspected supported API

`hyprctl -j version`, `hyprctl -j getoption <dotted-key>` return typed JSON.
Only generated fixed-key `hyprctl eval` code calls `hl.get_config` for guarded
compare-before-write and `hl.config({["known.dotted.key"]=literal})` for settings.
Gap tables use named `top/right/bottom/left`, not positional arrays in Lua.
No `repl`, print, shell evaluation, arbitrary Lua, dispatcher, reload or installer
is invoked. Strings use escaped decimal UTF-8 bytes, not invalid Lua JSON `\u`
escapes. Installed source and pinned matching C++ bindings were inspected before
choosing these methods; exact hashes/receipts are in NOTICE.backend.md.

## Transaction and recovery

Per-plugin/per-instance files under
`${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-<slug>/<sha256(instance)[:24]>/`.
Plugin/session directories must be user-owned mode 0700, not symlinks. Lock and
state are private. Snapshot is bounded JSON, written using a mode-0600 temporary
file, fsync, atomic replace and directory fsync before mutation. A nonblocking
flock serializes Apply/Restore/Keep. A complete first snapshot retains actual
values across subsequent presets; no fabricated defaults are used for rollback.

A pending journal records both pre-transaction and planned values. Every setter
checks all allowed current values inside compositor Lua; a final readback confirms
success. Partial mutation or post-mutation persistence failure attempts guarded
rollback to the immediately previous runtime values. Failed rollback retains the
journal. A later explicit Restore can recover interrupted mixed previous/target
values. Active snapshots require exact expected-value agreement. Divergent
external edits cause refusal, not silent overwrite. Unrelated keys are untouched.
Restore accepts the literal `restore:last` alias or any currently known row ID
and restores the **first session snapshot**, not the selected row's defaults.
The alias is valid only with `--verb restore --apply`; Apply/Keep cannot use it.
It resolves to the saved preset identity after the same bounded receipt, session,
lock and external-edit checks, without depending on a visible/filtered UI row.
After successful Restore the snapshot is removed; a second Restore reports no snapshot.

This is value-level optimistic conflict detection, not a global compositor lock:
ABA edits returning to the same values cannot be distinguished. Restoring values
does not restore Hyprland's `setByUser` diagnostic bookkeeping. Config reloads,
external toggle writers or another plugin can cause a deliberate conflict. No
boot/user configuration file is rewritten. IPC/service loss can leave a pending
journal; do not delete it to hide a failure. Resolve differing owned values first
and retry Restore; never force-overwrite an external edit automatically.

## Bounds and verification

Preset JSON and each IPC reply are limited to 64 KiB; at most 64 rows, unique
IDs <=64 chars, labels <=128, details <=512. Each helper call has a 3-second
wall timeout and bounded incremental pipes, and kills its owned process group on
timeout/overflow (including a child that closes stdout then hangs). No stderr or
private response body is dumped to UI. Parent owns the overall 30s action deadline;
a parent hard-kill during a multi-field outage leaves its pending journal for
explicit recovery rather than claiming success. No action test touched live IPC.

Run from this project:

```
TMPDIR="${TMPDIR:?Set TMPDIR to an existing private scratch directory}" env -u PYTHONPATH /usr/bin/python3 scripts/run-tests.py --backend-only
```

The runner uses offline bwrap, cleared environment, a fresh fake HOME, hidden
/run and real HOME, no display/session sockets, readonly /usr and source. Inside:
`env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v`.
The fake `hyprctl` executes actual generated code with system Lua against a fake
`hl` object and persists observable fake compositor state. It is logic/transport
fixture evidence, not proof that a real C++ compositor or GPU accepted an effect.

Current suite has **36 tests**. RED/GREEN logs, frozen backend/test
sources, hashes and final results are recorded under
`release-output/ponytail-fixes-1793557687154573167/`; earlier receipts remain
immutable historical evidence. These runs use `scripts/run-tests.py --backend-only`.
An active-state write can publish successfully and then fail its directory fsync.
Before any compensating setter, the original pending intent is saved again with
the actual pre-transaction values. If that save fails, compensation does not start.
A caller killed during compensation therefore leaves a pending journal owning
its mixed previous/target values, not an active journal falsely flagging its own
rollback as an external edit. The first baseline remains unchanged, including
when a failed explicit Restore started from an already interrupted mixture.
This is fault-injection/process-kill evidence, not a power-loss durability claim.

## Workspace-specific scope

Rows: `efficiency`, `compact`, `comfortable`. These are global runtime workspace
**appearance** preferences, not per-workspace app arrangements or saved sessions.
Allowlist: `general.gaps_in`, `general.gaps_out` (four nonnegative integer sides,
0–10000); `general.border_size`, `decoration.rounding` (integers 0–100);
`decoration.blur.enabled`, `decoration.shadow.enabled` (booleans).
Asymmetric gap snapshots restore all four actual sides, not fabricated defaults.
No layouts, monitors, binds, window rules, opacity floats, app launches, moves or
kills. Animations remain entirely untouched, including existing reduced motion.

## Not qualified here

No visible/native compositor setters, GUI, installed/enabled plugin, package
installation, config rewrite or external publication. Parent owns native Qt/QML,
headless compositor qualification and packaging. A green fake-provider suite is
not live/GPU/rendering/accessibility certification. Source receipts preserve RED
and GREEN iterations; earlier failed/incomplete receipts are not overwritten.
