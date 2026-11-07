# FM Tactics Creator

Create a native Football Manager `.fmf` variant from a native template you already own. Change its name, mentality, team tackling selection and stored defensive-line height. Formations, phase roles, player instructions and every unrequested tactic byte stay inherited from the template.

## Install

Install the public release:

```bash
uv tool install --python 3.12 https://github.com/jamespheffernan/fm-tactics-creator/releases/download/v0.1.2/fm_tactics_creator-0.1.2-py3-none-any.whl
```

Install the optional Pi addon:

```bash
pi install git:github.com/jamespheffernan/fm-tactics-creator@v0.1.2
```

Python 3.12 or later is required. You can also install a downloaded wheel with either:

```bash
uv tool install ./fm_tactics_creator-0.1.2-py3-none-any.whl
```

```bash
python -m pip install ./fm_tactics_creator-0.1.2-py3-none-any.whl
```

The package installs `cryptography` and `zstandard`. It runs without another project checkout, FM MCP, credentials or an AI account.

## Create a tactic

```bash
fm-tactics inspect --template "My template.fmf" --json
fm-tactics create --template "My template.fmf" --output "My positive tactic.fmf" \
  --name "My Positive Tactic" --mentality positive --tackling stay-on-feet
```

The command writes the new `.fmf` and an adjacent `.receipt.json`. It refuses existing output files and preserves the template. Use `--template-sha256 HASH` to require the exact template returned by inspection. Add `--json` for machine-readable results; failures return JSON on stderr and exit code 2.

## Save directly to FM27

Preview the exact destination, then create the new file:

```bash
fm-tactics create --template "My template.fmf" --fm27-folder --name "My Positive Tactic" \
  --mentality positive --tackling stay-on-feet --preview
fm-tactics create --template "My template.fmf" --fm27-folder --name "My Positive Tactic" \
  --mentality positive --tackling stay-on-feet
```

`--fm27-folder` requires `--name` and cannot be combined with `--output`. It uses FM27's platform directory: `~/Library/Application Support/Sports Interactive/Football Manager 27/Tactics` on macOS, `~/Documents/Sports Interactive/Football Manager 27/tactics` on Windows, and `~/.local/share/Sports Interactive/Football Manager 27/tactics` on Linux. The FM27 parent directory must exist; creation can add its missing Tactics child. A missing game directory produces an error rather than selecting another location.

For a custom location, pass `--tactics-dir "/your/FM27/tactics"` or set `FM27_TACTICS_DIR` to that exact existing tactics directory. The flag takes precedence over the environment variable. Template discovery also honors `FM27_TACTICS_DIR`; `templates --directory` overrides it. `--output` continues to use the exact path you supply.

Folder mode derives a single filename from the tactic name, normalizes Unicode, rejects path separators and refuses existing or equivalent filenames. Receipts go into the hidden `.fm-tactics-receipts` child directory. `--output` keeps its adjacent receipt. `--preview --json` reports both paths and the source hash without creating files or directories.

Omit `--mentality` or `--tackling` to inherit that selection. Mentalities are `very-defensive`, `defensive`, `cautious`, `balanced`, `positive`, `attacking` and `very-attacking`. Tackling options are `get-stuck-in`, `stay-on-feet` and `none`; `none` clears both explicit flags and does not assert an effective Standard default.

Discover local templates with `fm-tactics templates`, or `fm-tactics templates --directory "/path/to/templates" --json`. Templates, game files and saves are supplied by you; none are bundled.

## Supported scope

This release supports the observed native `cat.` schema 0x44 with source major version 26 or 27. It creates template variants. Custom formations, role changes and team instruction edits beyond tackling and defensive-line height are unsupported.

Every creation checks archive roundtrip and reverses the requested edits to prove that all other tactic bytes survived. The upstream writer was tested with six originals and eighteen variants through the isolated FM27 native body reader to exact EOF, including seven mentalities and all three stored tackling selections. Those earlier body-reader controls did not include the defensive-line edit. Defensive-line validation includes offline archive roundtrip and exact preservation checks; its interactive game import remains unverified. Packaged-product release checks are recorded separately. Native body-reader acceptance is stronger than structural parsing; it remains separate from interactive import and match-engine testing. The tool never launches, controls or writes to a running game.

## License

Proprietary software, copyright James Heffernan. See LICENSE. The existing license is preserved; this release does not grant an open-source license. Codec source provenance is recorded in PROVENANCE.json.

Defensive-line height is an optional stored edit: `--defensive-line higher` selects Higher Defensive Line; `much-higher`, `lower` and `much-lower` select the other named heights. Omit the option to inherit. `none` clears the four explicit height flags without asserting an effective Standard/default. `inspect`, template listing, preview and generation receipts report `defensive_line`; preview and receipts distinguish inheritance from an explicit change. Other team selections, including the line of engagement, remain inherited. Use `create --preview` to validate without writing.

If a template stores conflicting defensive-line heights, inspection reports `defensive_line: null` and `defensive_line_state: conflicting_stored_selections`. Unrelated edits and inherited previews preserve those bits. That template’s `supported_edits` omits defensive-line height, and attempts to change it are rejected.
