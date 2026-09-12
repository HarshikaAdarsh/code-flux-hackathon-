#!/usr/bin/env node
/**
 * Runs the backend and frontend together with one command.
 *
 *   npm run dev            both
 *   npm run dev -- --api   backend only
 *   npm run dev -- --web   frontend only
 *   npm run dev -- --no-db skip starting the Postgres container
 *
 * Checks the things that have actually broken before: a missing virtualenv,
 * a port still held by an earlier run, and a stopped database container.
 */

import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import {
  API_PORT, CLIENT, IS_WIN, ROOT, SERVER, WEB_PORT,
  color, fail, info, killTree, ok, pidsOnPort, portBusy, processName, venvPython, warn,
} from './lib.mjs';

const args = process.argv.slice(2);
const only = args.includes('--api') ? 'api' : args.includes('--web') ? 'web' : 'both';
const skipDb = args.includes('--no-db');

const wantApi = only === 'both' || only === 'api';
const wantWeb = only === 'both' || only === 'web';

/* ------------------------------ preflight ------------------------------ */

async function preflight() {
  let bad = false;

  if (wantApi && !existsSync(venvPython())) {
    fail('\nThe backend virtualenv is missing.');
    info('Create it with:');
    info(color('cyan', '  npm run setup'));
    bad = true;
  }

  if (wantWeb && !existsSync(`${CLIENT}/node_modules`)) {
    fail('\nThe frontend dependencies are not installed.');
    info('Install them with:');
    info(color('cyan', '  npm run setup'));
    bad = true;
  }

  const checks = [];
  if (wantApi) checks.push(['backend', API_PORT]);
  if (wantWeb) checks.push(['frontend', WEB_PORT]);

  for (const [label, port] of checks) {
    if (await portBusy(port)) {
      const pids = pidsOnPort(port);
      fail(`\nPort ${port} (${label}) is already in use.`);
      if (pids.length) {
        for (const pid of pids) info(`  held by ${processName(pid)} (PID ${pid})`);
      }
      info('Free it with:');
      info(color('cyan', '  npm run stop'));
      bad = true;
    }
  }

  if (bad) {
    info('');
    process.exit(1);
  }
}

/* ------------------------------- database ------------------------------ */

function startDatabase() {
  if (!wantApi || skipDb) return;
  const res = spawnSync('docker', ['compose', 'up', '-d'], {
    cwd: SERVER,
    stdio: 'pipe',
    encoding: 'utf8',
  });
  if (res.status === 0) {
    ok('database  Postgres container is up');
  } else {
    warn('database  could not start the Postgres container.');
    warn(`          ${(res.stderr || res.error?.message || '').trim().split('\n')[0]}`);
    warn('          The API will start but every request will fail until it is running.');
  }
}

/* ------------------------------ processes ------------------------------ */

const children = [];
let shuttingDown = false;

function pipe(stream, tag, tint) {
  let buffer = '';
  stream.on('data', (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (line.trim()) console.log(`${color(tint, tag.padEnd(8))}  ${line}`);
    }
  });
}

function launch(name, tint, command, cmdArgs, cwd) {
  const child = spawn(command, cmdArgs, {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: !IS_WIN, // gives us a process group to kill on POSIX
  });

  pipe(child.stdout, name, tint);
  pipe(child.stderr, name, tint);

  child.on('error', (err) => {
    fail(`${name}: failed to start — ${err.message}`);
    shutdown(1);
  });

  child.on('exit', (code) => {
    if (shuttingDown) return;
    const how = code === 0 ? 'stopped' : `exited with code ${code}`;
    warn(`\n${name} ${how}. Shutting the other process down too.`);
    shutdown(code ?? 1);
  });

  children.push(child);
  return child;
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (child.pid && child.exitCode === null) killTree(child.pid);
  }
  setTimeout(() => process.exit(code), 250);
}

process.on('SIGINT', () => {
  info('\nStopping…');
  shutdown(0);
});
process.on('SIGTERM', () => shutdown(0));

/* --------------------------------- run --------------------------------- */

await preflight();
startDatabase();

info('');
if (wantApi) {
  launch('api', 'cyan', venvPython(), [
    '-m', 'uvicorn', 'app.main:app',
    '--reload', '--host', '127.0.0.1', '--port', String(API_PORT),
  ], SERVER);
}
if (wantWeb) {
  // Run Vite's own entrypoint rather than `npm run dev`: spawning npm.cmd
  // needs shell:true on Windows, which Node now warns about and which makes
  // the process tree harder to kill cleanly.
  launch('web', 'magenta', process.execPath, [path.join(CLIENT, 'node_modules', 'vite', 'bin', 'vite.js')], CLIENT);
}

info('');
if (wantWeb) ok(`  frontend   http://localhost:${WEB_PORT}`);
if (wantApi) ok(`  backend    http://127.0.0.1:${API_PORT}  (docs at /docs)`);
info(color('dim', '\n  Ctrl+C stops everything.\n'));
