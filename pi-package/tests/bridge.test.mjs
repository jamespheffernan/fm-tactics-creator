import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, chmodSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runTacticCreator } from '../extensions/fm-tactics.mjs';

test('folder mode forwards explicit flags without inventing an output path; legacy paths and hash pin remain intact', async () => {
  const scratch = mkdtempSync(join(tmpdir(), 'pi-fm-destination-'));
  const previous = process.env.FM_TACTICS_COMMAND;
  try {
    const cli = join(scratch, 'fm-tactics');
    const calls = join(scratch, 'calls.jsonl');
    writeFileSync(cli, `#!/usr/bin/env node\nimport {appendFileSync} from 'node:fs';\nconst args=process.argv.slice(2);appendFileSync(${JSON.stringify(calls)},JSON.stringify(args)+'\\n');console.log(JSON.stringify(args[0]==='inspect'?{template_sha256:'a'.repeat(64)}:{args}));\n`);
    chmodSync(cli, 0o755);
    process.env.FM_TACTICS_COMMAND = cli;
    const base = { action: 'create', template_path: '/user/template.fmf', template_sha256: 'a'.repeat(64), name: 'Literal $(name)', mentality: 'positive', tackling: 'stay-on-feet' };
    const folder = await runTacticCreator({ ...base, fm27_folder: true, tactics_directory: '/user/Custom Tactics', preview: true });
    assert.ok(folder.args.includes('--fm27-folder'));
    assert.ok(folder.args.includes('--preview'));
    assert.equal(folder.args[folder.args.indexOf('--tactics-dir') + 1], '/user/Custom Tactics');
    assert.ok(!folder.args.includes('--output'));
    assert.equal(folder.args[folder.args.indexOf('--name') + 1], 'Literal $(name)');
    assert.equal(folder.args[folder.args.indexOf('--template-sha256') + 1], base.template_sha256);
    const explicit = await runTacticCreator({ ...base, output_path: '/user/chosen.fmf' });
    assert.equal(explicit.args[explicit.args.indexOf('--output') + 1], '/user/chosen.fmf');
    assert.ok(!explicit.args.includes('--fm27-folder'));
    await assert.rejects(() => runTacticCreator({ ...base, fm27_folder: true, output_path: '/conflict.fmf' }), /not both/);
    await assert.rejects(() => runTacticCreator({ ...base, output_path: '/chosen.fmf', tactics_directory: '/invalid' }), /requires/);
    await assert.rejects(() => runTacticCreator({ ...base, fm27_folder: true, template_sha256: 'b'.repeat(64) }), /changed/);
    const recorded = readFileSync(calls, 'utf8').trim().split('\n').map(JSON.parse);
    assert.equal(recorded.filter(args => args[0] === 'create').length, 2);
  } finally {
    if (previous === undefined) delete process.env.FM_TACTICS_COMMAND;
    else process.env.FM_TACTICS_COMMAND = previous;
    rmSync(scratch, { recursive: true, force: true });
  }
});
