#!/usr/bin/env node
/**
 * One-time setup: Python virtualenv + backend deps, frontend deps, .env files,
 * and the sandbox runner image.
 *
 *   npm run setup
 */

import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { CLIENT, IS_WIN, SERVER, color, fail, info, ok, venvPython, warn } from './lib.mjs';

function run(label, command, args, cwd) {
  info(color('cyan', `\n▸ ${label}`));
  const res = spawnSync(command, args, { cwd, stdio: 'inherit', shell: IS_WIN });
  if (res.status !== 0) {
    fail(`  ${label} failed.`);
    return false;
  }
  return true;
}

function seedEnv(dir) {
  const env = path.join(dir, '.env');
  const example = path.join(dir, '.env.example');
  if (!existsSync(env) && existsSync(example)) {
    copyFileSync(example, env);
    ok(`  created ${path.relative(process.cwd(), env)} from .env.example`);
    return true;
  }
  return false;
}

/* --- backend --- */
if (!existsSync(venvPython())) {
  const python = IS_WIN ? 'python' : 'python3';
  if (!run('Creating the Python virtualenv', python, ['-m', 'venv', '.venv'], SERVER)) process.exit(1);
} else {
  ok('\n▸ Python virtualenv already exists');
}
if (!run('Installing backend dependencies', venvPython(), ['-m', 'pip', 'install', '-q', '-r', 'requirements.txt'], SERVER)) {
  process.exit(1);
}

/* --- env files --- */
info(color('cyan', '\n▸ Configuration'));
const seededServer = seedEnv(SERVER);
seedEnv(CLIENT);
if (seededServer) {
  warn('  Add your GEMINI_API_KEY and GROQ_API_KEY to server/.env before using AI features.');
  warn('  Keys: https://aistudio.google.com/app/apikey  and  https://console.groq.com/keys');
} else {
  ok('  server/.env already present');
}

/* --- database + migrations --- */
if (run('Starting Postgres', 'docker', ['compose', 'up', '-d'], SERVER)) {
  // give the container a moment to accept connections before migrating
  spawnSync(IS_WIN ? 'timeout' : 'sleep', IS_WIN ? ['/t', '6', '/nobreak'] : ['6'], { stdio: 'ignore', shell: IS_WIN });
  run('Applying database migrations', venvPython(), ['-m', 'alembic', 'upgrade', 'head'], SERVER);
} else {
  warn('  Is Docker Desktop running? The API needs Postgres.');
}

/* --- sandbox image --- */
info(color('cyan', '\n▸ Code sandbox image (for coding assessments)'));
spawnSync('docker', ['pull', 'python:3.12-slim'], { stdio: 'inherit', shell: IS_WIN });

/* --- frontend --- */
run('Installing frontend dependencies', IS_WIN ? 'npm.cmd' : 'npm', ['install'], CLIENT);

ok('\nSetup complete. Start everything with:');
info(color('cyan', '  npm run dev\n'));
