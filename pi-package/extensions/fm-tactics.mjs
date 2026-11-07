import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const mentalities = ['very-defensive', 'defensive', 'cautious', 'balanced', 'positive', 'attacking', 'very-attacking'];
const tackling = ['stay-on-feet', 'get-stuck-in', 'none'];

async function invoke(args, signal) {
  const command = process.env.FM_TACTICS_COMMAND || 'fm-tactics';
  try {
    const { stdout } = await execFileAsync(command, [...args, '--json'], {
      signal, timeout: 60000, maxBuffer: 2 * 1024 * 1024, windowsHide: true,
    });
    return JSON.parse(stdout);
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('Install the FM Tactics Creator Python wheel and put fm-tactics on PATH, or set FM_TACTICS_COMMAND to its executable path.');
    if (error.stderr?.trim()) {
      let detail = error.stderr.trim();
      try { detail = JSON.stringify(JSON.parse(detail)); } catch {}
      throw new Error(detail);
    }
    throw error;
  }
}

function required(params, key) {
  if (typeof params[key] !== 'string' || !params[key].trim()) throw new Error(`${key} is required.`);
  return params[key];
}

export async function runTacticCreator(params, signal) {
  if (params.action === 'templates') {
    return invoke(['templates', ...(params.directory ? ['--directory', params.directory] : [])], signal);
  }
  const template = required(params, 'template_path');
  if (params.action === 'inspect') return invoke(['inspect', '--template', template], signal);
  if (params.action !== 'create') throw new Error('Unknown action. Use templates, inspect or create.');
  const expected = required(params, 'template_sha256');
  if (!/^[a-f0-9]{64}$/i.test(expected)) throw new Error('template_sha256 must be the 64-character SHA256 returned by inspect.');
  const inspected = await invoke(['inspect', '--template', template], signal);
  if (inspected.template_sha256?.toLowerCase() !== expected.toLowerCase()) throw new Error('Template changed since inspection. Inspect it again before creating the file.');
  const args = ['create', '--template', template, '--template-sha256', expected, '--output', required(params, 'output_path'), '--name', required(params, 'name')];
  if (params.mentality !== undefined) {
    if (!mentalities.includes(params.mentality)) throw new Error('Unsupported mentality.');
    args.push('--mentality', params.mentality);
  }
  if (params.tackling !== undefined) {
    if (!tackling.includes(params.tackling)) throw new Error('Unsupported tackling selection.');
    args.push('--tackling', params.tackling);
  }
  return invoke(args, signal);
}

export default function (pi) {
  pi.registerTool({
    name: 'fm_tactics',
    label: 'FM Tactics Creator',
    description: 'Inspect a user-supplied native .fmf tactic and create a new standalone native file with a new name, optional mentality and tackling selection. First inspect the template and pass its SHA256 to create. Formations, roles and unrequested instructions are inherited. The none tackling selection clears explicit flags; it does not establish an effective default. Requires the standalone fm-tactics CLI. Writes only the requested new output and receipt; existing outputs are not overwritten. Does not read or control a running game. Decode/roundtrip validation is not proof of in-game import compatibility.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        action: { type: 'string', enum: ['templates', 'inspect', 'create'] },
        directory: { type: 'string', description: 'User-supplied directory to search for templates.' },
        template_path: { type: 'string', description: 'Path to the user-supplied native .fmf template.' },
        template_sha256: { type: 'string', description: 'Exact SHA256 returned by inspect; required to create.' },
        output_path: { type: 'string', description: 'New output .fmf path selected by the user; required to create.' },
        name: { type: 'string', description: 'New tactic name; required to create.' },
        mentality: { type: 'string', enum: mentalities },
        tackling: { type: 'string', enum: tackling },
      },
      required: ['action'],
    },
    async execute(_id, params, signal) {
      try {
        const details = await runTacticCreator(params, signal);
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
      } catch (error) {
        return { content: [{ type: 'text', text: `FM Tactics Creator: ${error.message}` }], details: { error: true }, isError: true };
      }
    },
  });
}
