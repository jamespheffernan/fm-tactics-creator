# FM Tactics Creator for Pi

Create native `.fmf` files from your own template using Pi. This package adds one tool, `fm_tactics`, and depends only on the standalone FM Tactics Creator CLI. It includes no tactics, game files, credentials or personal adviser configuration.

Install the Python wheel supplied with this release into your environment, then install the versioned Pi package directly from GitHub:

```sh
python3 -m pip install /path/to/fm_tactics_creator-0.1.0-py3-none-any.whl
pi install git:github.com/jamespheffernan/fm-tactics-creator@v0.1.0
```

Make `fm-tactics` available on `PATH`. If you installed the wheel in a virtual environment, activate that environment before launching Pi, or set `FM_TACTICS_COMMAND` to its `fm-tactics` executable path. The variable names one executable, not a shell command. To install a downloaded, extracted package instead, use `pi install /path/to/pi-fm-tactics-creator`.

Try a one-session installation without changing Pi settings:

```sh
pi -e git:github.com/jamespheffernan/fm-tactics-creator@v0.1.0
```

Example prompt:

> Inspect my template at `/path/to/template.fmf`. Create `/path/to/New Tactic.fmf`, named New Tactic, with Positive mentality. Keep the formations, roles and other instructions.

The tool inspects the template before creation and requires its SHA256. Mentality and tackling are optional; omission inherits the template. Tackling `none` clears the explicit flags without claiming an effective default. Existing output files are refused.

The result contains the output path, receipt path and verification details. The running game is untouched. Native decode and roundtrip checks do not prove that a particular game build will import the file.
