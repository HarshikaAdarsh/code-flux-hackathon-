/* Shared helpers for the dev/stop launchers. Zero dependencies. */

import { execFileSync, spawnSync } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const SERVER = path.join(ROOT, 'server');
export const CLIENT = path.join(ROOT, 'client');
export const IS_WIN = process.platform === 'win32';

export const API_PORT = 8000;
export const WEB_PORT = 5173;

const C = {
  reset: '\x1b[0m', dim: '\x1b[2m', bold: '\x1b[1m',
  red: '\x1b[31m', green: '\x1b[32m', yellow: '\x1b[33m',
  blue: '\x1b[34m', magenta: '\x1b[35m', cyan: '\x1b[36m',
};
export const color = (c, s) => `${C[c] || ''}${s}${C.reset}`;

export const info = (s) => console.log(s);
export const warn = (s) => console.log(color('yellow', s));
export const fail = (s) => console.log(color('red', s));
export const ok = (s) => console.log(color('green', s));

/** Path to the backend virtualenv's python, per platform. */
export const venvPython = () =>
  IS_WIN
    ? path.join(SERVER, '.venv', 'Scripts', 'python.exe')
    : path.join(SERVER, '.venv', 'bin', 'python');

/**
 * True if something is already accepting connections on the port.
 * Connect-based rather than bind-based: Vite listens on ::1 and uvicorn on
 * 127.0.0.1, and a bind test on the wrong family reports a free port.
 */
export function portInUse(port, host = '127.0.0.1', timeout = 700) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const done = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeout);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
    socket.connect(port, host);
  });
}

/** Check both loopback families — either one being busy blocks a bind. */
export async function portBusy(port) {
  return (await portInUse(port, '127.0.0.1')) || (await portInUse(port, '::1'));
}

/** PIDs listening on a port. Windows: netstat; POSIX: lsof. */
export function pidsOnPort(port) {
  try {
    if (IS_WIN) {
      const out = execFileSync('netstat', ['-ano'], { encoding: 'utf8' });
      // No '-p tcp' filter: it drops IPv6 listeners, and Vite binds [::1].
      const pids = new Set();
      for (const line of out.split(/\r?\n/)) {
        if (!/LISTENING/i.test(line)) continue;
        const cols = line.trim().split(/\s+/);
        const local = cols[1] || '';
        if (local.endsWith(`:${port}`)) pids.add(cols[cols.length - 1]);
      }
      return [...pids].filter((p) => p && p !== '0');
    }
    const out = execFileSync('lsof', ['-ti', `tcp:${port}`, '-sTCP:LISTEN'], { encoding: 'utf8' });
    return out.split('\n').map((s) => s.trim()).filter(Boolean);
  } catch {
    return [];
  }
}

export function processName(pid) {
  try {
    if (IS_WIN) {
      const out = execFileSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], { encoding: 'utf8' });
      return (out.split(',')[0] || '').replace(/"/g, '').trim() || 'unknown';
    }
    return execFileSync('ps', ['-p', pid, '-o', 'comm='], { encoding: 'utf8' }).trim() || 'unknown';
  } catch {
    return 'unknown';
  }
}

/** Kill a process and its children (npm spawns the real server as a child). */
export function killTree(pid) {
  try {
    if (IS_WIN) spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
    else process.kill(-pid, 'SIGKILL');
    return true;
  } catch {
    try {
      process.kill(pid, 'SIGKILL');
      return true;
    } catch {
      return false;
    }
  }
}
