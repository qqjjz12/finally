// Starts the backend locally with a fresh temp DB, mock LLM, and the built frontend.
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const dir = mkdtempSync(path.join(tmpdir(), 'finally-e2e-'));
const child = spawn('uv', ['run', 'uvicorn', 'app.main:app', '--port', process.env.E2E_PORT || '8765'], {
  cwd: path.join(root, 'backend'),
  stdio: 'inherit',
  env: {
    ...process.env,
    FINALLY_STATIC_DIR: path.join(root, 'frontend', 'out'),
    FINALLY_DB_PATH: path.join(dir, 'finally.db'),
    LLM_MOCK: 'true',
    MASSIVE_API_KEY: '',
  },
});
const stop = () => {
  child.kill();
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
child.on('exit', (c) => process.exit(c ?? 0));
