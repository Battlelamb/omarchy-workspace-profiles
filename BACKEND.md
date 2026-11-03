# Workspace Profiles backend · v0.4.1

## Commands and schema

Exact advertised actions: `apply`, `restore`, `favorite`, `capture`, `import`, `export-preset`, `compare`.

```
/usr/bin/python3 runtime/0.4.1/backend.py catalog
/usr/bin/python3 runtime/0.4.1/backend.py action --id compact-coding --verb compare --apply
/usr/bin/python3 runtime/0.4.1/backend.py action --id compact-coding --verb apply --apply
/usr/bin/python3 runtime/0.4.1/backend.py action --id restore:last --verb restore --apply
/usr/bin/python3 runtime/0.4.1/backend.py preferences --apply --payload '{"options":{"showDiffs":false}}'
```

The five named appearance modes are `compact-coding`, `focused-writing`, `spacious`, `presentation`, `low-effects`. Existing `efficiency`, `compact`, `comfortable` IDs remain valid. Allowlist: `general.gaps_in`/`general.gaps_out` are four integer side values 0–10000; `general.border_size`/`decoration.rounding` are integers 0–100; `decoration.blur.enabled`/`decoration.shadow.enabled` are booleans. Every built-in and every custom import contains **exactly these six** values. No animation, workspace layout/assignment, app movement, monitor, shader, command or session-manager field is accepted.

Export example (all fields mandatory):

```json
{"version":1,"slug":"workspace-profiles","name":"Presentation copy","settings":{"general.gaps_in":[0,0,0,0],"general.gaps_out":[0,0,0,0],"general.border_size":5,"decoration.rounding":0,"decoration.blur.enabled":false,"decoration.shadow.enabled":false}}
```

No timed-preview action is advertised for workspace profiles: Apply and explicit Restore are the supported operations. Closing the panel does not auto-restore.

## Scoped Compare and Apply

Saved `applyScope` is enum `all` (default), `spacing-only`, `effects-only`.
Spacing admits exactly `general.gaps_in`, `general.gaps_out`, and
`general.border_size`; effects admits exactly `decoration.rounding`,
`decoration.blur.enabled`, and `decoration.shadow.enabled`. Compare and Apply
share the same selector over validated settings. Apply merges that subset into
fresh complete current values; only changed subset keys reach setters.

Capture/export/import remain complete six-setting typed data. Journals,
compare-before-write guards, first baseline and Restore remain full-width;
changing the preference never narrows Restore or external-divergence refusal.
This deliberately retains refusal for a divergent edit outside today's scope.
Partial failure compensates only values this transaction could have written,
including when a setter changed state but lost its acknowledgement.

```
/usr/bin/python3 runtime/0.4.1/backend.py preferences --apply --payload '{"options":{"applyScope":"spacing-only"}}'
/usr/bin/python3 runtime/0.4.1/backend.py action --id compact-coding --verb compare --apply
```

## Provider and trust boundary

System `/usr/bin/python3`, Python standard library and installed `hyprctl`; the adapter is qualified for **Hyprland Lua 0.56.2 only** and rejects other versions. Runtime paths derive from `__file__`, never cwd. Each package includes its own runtime helpers; no sibling plugin is required. Native shell code is unsandboxed at runtime; the development runner is not a runtime security sandbox.

Only `hyprctl -j version`, `hyprctl -j getoption <allowlisted dotted key>` and generated fixed-key `hyprctl eval` are used. Generated Lua uses `hl.get_config` for compare-before-write and `hl.config({[known_key]=typed_literal})` for mutation. Gap tables have named `top/right/bottom/left` fields. Strings use decimal-escaped UTF-8 bytes. No `repl`, bare print, arbitrary Lua, shell evaluation, dispatcher, installer, reload or configuration-file rewrite is used.

Every write/action requires `--apply`; success is JSON with `ok:true`, failure is nonzero JSON with plain bounded text and no traceback. Unexpected options, inappropriate payloads and invalid membership fail closed. CLI payloads are JSON objects limited to **16384 UTF-8 bytes**; duplicate keys, nonfinite numbers, malformed Unicode and nesting beyond 12 levels are rejected. ID strings never become commands or output paths. Catalogue reads do no IPC or writes and expose fresh rows, `preferences` and `settingsSchema`.

## v0.4.0 display preferences

The exact enum keys are `density` (`comfortable` default, `compact`), `layout`
(`list` default, `grid`), and `sortOrder` (`default` default, `name`,
`favorites-first`). They affect native catalogue presentation only. Existing
stores without these keys receive defaults without an implicit write; Reset
returns those defaults. The UI owns stable sorting and fresh action admission.
All settings writes remain local preference operations, never compositor setters.

## Preferences

`PREFERENCE_SCHEMA` is passed to the bundled `preferences.py` helper's exact `read`, `change`, `reset`, `toggle`, `remember` APIs. Storage is `${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/lego/<slug>/preferences.json`, outside the installed source. The helper bounds reads, rejects unsafe files/ancestor symlinks, locks updates and uses fsync plus atomic replacement. Corrupt preferences are not silently reset.

```
/usr/bin/python3 runtime/0.4.1/backend.py preferences
/usr/bin/python3 runtime/0.4.1/backend.py preferences --apply --payload '{"reset":true}'
/usr/bin/python3 runtime/0.4.1/backend.py preferences --apply --payload '{"favorites":["known-id"],"collections":{"Desk":["known-id"]}}'
```

Reads return `{ok,preferences,settingsSchema,message}`. Patches accept only `options`, `favorites`, `collections`; recent/version cannot be written. Reset is the sole-key `{reset:true}` request and resets **only preferences**, never custom presets, generated effects or transaction journals. Favorites may retain stale IDs inertly; Favorite actions require fresh membership. Recents update only after confirmed Apply/Preview/export. If recent persistence fails after an externally confirmed action, success remains truthful with a warning rather than reporting an invented action failure.

## Transaction and Restore invariants

Journals live under `${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-<slug>/<sha256(instance)[:24]>/`. Plugin and session directories must be user-owned private directories, not symlinks. A nonblocking flock serializes transactions. A bounded pending journal is fsynced and atomically replaced before any setter, retaining the first actual `before`, immediately previous actual values and planned target. A final compositor readback confirms success.

Each setter guards all owned current values inside compositor Lua. Partial failures compensate only values this transaction could have written, in reverse order. Active publication uses a separate record: it cannot mutate the in-memory pending intent. Before compensation, that original pending intent must be durably republished even when active replace succeeded but acknowledgement/fsync failed. If that persistence fails, no compensating setter runs. Lost compensation acknowledgement leaves a pending journal recoverable from the real previous/target mixture, not a fabricated baseline. Failed compensation retains the receipt and reports failure.

Restore accepts any freshly known row or the exact `restore:last` alias, **only with Restore**. The exact alias/Restore pair follows only the validated receipt without loading the catalogue, so a missing, corrupt or unsafe custom store cannot block recovery; Other actions and imports still require their normal validation. Active state must exactly match expected values; interrupted pending state accepts only per-key previous/target mixtures. Divergent external values block Restore/timeout without clobbering the values or journal. Unrelated options remain untouched. Successful Restore removes the receipt; a second Restore fails honestly.

This is optimistic value-level conflict detection, not a global compositor lock. Same-value **ABA edits cannot be distinguished**. Restore does not restore `setByUser` diagnostics or undo arbitrary normal provider side effects. External writers, another plugin and config reloads may create deliberate conflicts. Resolve those explicitly and retry Restore; do not delete a journal to hide failure.

Each IPC reply and preset/journal read is bounded to 64 KiB. JSON file reads use nofollow/nonblocking descriptors, require regular files, check metadata stability, reject duplicates/nonfinite/deep JSON and read at most cap+1. Each helper call has a three-second wall timeout, incremental output cap and owned-process-group kill, including helpers that close stdout then hang. Overall UI cancellation/watchdog admission belongs to the native controller; accepted external work cannot be revoked by closing a panel.

## Offline verification

Run from this checkout, with an existing approved private scratch directory:

```
TMPDIR="${TMPDIR:?Set an existing private scratch directory}" env -u PYTHONPATH PATH=/usr/bin /usr/bin/python3 scripts/run-tests.py --backend-only
```

The shipped runner uses offline bwrap, unshared network, cleared environment, fresh fake HOME, hidden real HOME and `/run`, no live display/compositor sockets, read-only source/system files and fake IPC. The fake `hyprctl` executes generated Lua with the installed system Lua against an observable fake `hl` object. This proves logic/transport, not C++ compositor/GPU integration. Full native/component gate: `bash test.sh` with the same TMPDIR. Historical validation records describe their original source versions, not current-source coverage.

## Named captures, strict import/export

```
/usr/bin/python3 runtime/0.4.1/backend.py action --id capture:current --verb capture --apply --payload '{"name":"My desk"}'
/usr/bin/python3 runtime/0.4.1/backend.py action --id <known-id> --verb export-preset --apply
/usr/bin/python3 runtime/0.4.1/backend.py action --id import:preset --verb import --apply --payload '<versioned preset JSON>'
```

Capture reads actual allowlisted compositor values but calls no setter and writes no recovery journal. Import validates before storage and does no IPC. Export returns `{ok,message,preset,detail,preferences?}` containing inert JSON, never writes to a caller-chosen output path and never evaluates data. Apply is a separate explicit operation after import.

Format: `{ "version":1, "slug":"workspace-profiles", "name":"My desk", "settings":{...typed allowlisted fields...} }`; no other top-level or setting keys. Names are 1–80 printable characters with no edge whitespace. IDs are `custom-<sha256(name)[:16]>`, never derived as filesystem paths. At most 32 custom presets fit in the fixed private `custom-presets.json` beside preferences. Existing names/collisions/full stores are refused, never overwritten. File symlinks, special files, hardlinks, wrong ownership, public modes, corruption and oversize data fail closed. Ancestor symlinks cannot redirect imports. Storage is locked, bounded to 64 KiB and atomically replaced using a private fsynced temporary file. Preferences Reset leaves it alone.

`compare` returns `{ok,message,diff:[{key,before,after}],detail}` with actual typed changes and no setters or journal. Numeric summaries are controlled by boolean option `showDiffs` (default true); this is a catalogue preference, not a compositor setting.

New preference writes have a separate aggregate limit of **128 KiB compact UTF-8
JSON**, checked under the store lock before mutation; rejection preserves existing
bytes. Per-field counts and the 16384-byte CLI payload limit do not increase that
aggregate. Legacy reads remain bounded to **16 MiB** and fully schema-validated,
allowing explicit Reset to shrink old valid stores without touching custom presets
or recovery journals. Reply JSON must be **strictly below 1 MiB** after UTF-8
serialization; with its terminating LF, the wire reply is **at most 1 MiB**,
matching the inclusive UI collector/parser budget. Oversized read snapshots fail
cleanly; an already confirmed action omits its optional preference snapshot with
a warning instead of fabricating an external-action failure. Ordinary preference
patches refuse an already oversized snapshot before mutation; explicit Reset
remains available.
