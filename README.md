# FM Tactics Creator

Create a native Football Manager `.fmf` variant from a native template you already own. Change its name, mentality and team tackling selection. Formations, phase roles, player instructions and every unrequested tactic byte stay inherited from the template.

## Install

Install the public release:

```bash
uv tool install --python 3.12 https://github.com/jamespheffernan/fm-tactics-creator/releases/download/v0.1.0/fm_tactics_creator-0.1.0-py3-none-any.whl
```

Install the optional Pi addon:

```bash
pi install git:github.com/jamespheffernan/fm-tactics-creator@v0.1.0
```

Python 3.12 or later is required. You can also install a downloaded wheel with either:

```bash
uv tool install ./fm_tactics_creator-0.1.0-py3-none-any.whl
```

```bash
python -m pip install ./fm_tactics_creator-0.1.0-py3-none-any.whl
```

The package installs `cryptography` and `zstandard`. It runs without another project checkout, FM MCP, credentials or an AI account.

## Create a tactic

```bash
fm-tactics inspect --template "My template.fmf" --json
fm-tactics create --template "My template.fmf" --output "My positive tactic.fmf" \
  --name "My Positive Tactic" --mentality positive --tackling stay-on-feet
```

The command writes the new `.fmf` and an adjacent `.receipt.json`. It refuses existing output files and preserves the template. Use `--template-sha256 HASH` to require the exact template returned by inspection. Add `--json` for machine-readable results; failures return JSON on stderr and exit code 2.

Omit `--mentality` or `--tackling` to inherit that selection. Mentalities are `very-defensive`, `defensive`, `cautious`, `balanced`, `positive`, `attacking` and `very-attacking`. Tackling options are `get-stuck-in`, `stay-on-feet` and `none`; `none` clears both explicit flags and does not assert an effective Standard default.

Discover local templates with `fm-tactics templates`, or `fm-tactics templates --directory "/path/to/templates" --json`. Templates, game files and saves are supplied by you; none are bundled.

## Supported scope

This release supports the observed native `cat.` schema 0x44 with source major version 26 or 27. It creates template variants. Custom formations, role changes and broader instruction edits are unsupported.

Every creation checks archive roundtrip and reverses the requested edits to prove that all other tactic bytes survived. The upstream writer was tested with six originals and eighteen variants through the isolated FM27 native body reader to exact EOF, including seven mentalities and all three stored tackling selections. Packaged-product release checks are recorded separately. Native body-reader acceptance is stronger than structural parsing; it remains separate from interactive import and match-engine testing. The tool never launches, controls or writes to a running game.

## License

Proprietary software, copyright James Heffernan. See LICENSE. The existing license is preserved; this release does not grant an open-source license. Codec source provenance is recorded in PROVENANCE.json.
