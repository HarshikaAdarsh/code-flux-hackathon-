#!/usr/bin/env node
/**
 * Frees the dev ports. Useful when a previous run was closed without Ctrl+C
 * and is still holding 8000 or 5173 — on Windows that surfaces as the very
 * unhelpful "WinError 10013: socket access forbidden".
 *
 *   npm run stop
 */

import { API_PORT, WEB_PORT, color, info, killTree, ok, pidsOnPort, portBusy, processName } from './lib.mjs';

let killed = 0;

for (const [label, port] of [['backend', API_PORT], ['frontend', WEB_PORT]]) {
  const busy = await portBusy(port);
  let pids = pidsOnPort(port);

  // A cascading shutdown elsewhere can free the port between these two
  // checks; give it a moment before calling the owner unidentifiable.
  if (busy && !pids.length) {
    await new Promise((r) => setTimeout(r, 600));
    pids = pidsOnPort(port);
    if (!pids.length && !(await portBusy(port))) {
      info(`${label.padEnd(9)} port ${port} already free`);
      continue;
    }
  }

  if (!busy && !pids.length) {
    info(`${label.padEnd(9)} port ${port} already free`);
    continue;
  }
  if (!pids.length) {
    info(color('yellow', `${label.padEnd(9)} port ${port} is in use but the owner could not be identified`));
    continue;
  }
  for (const pid of pids) {
    const name = processName(pid);
    if (killTree(pid)) {
      killed += 1;
      ok(`${label.padEnd(9)} stopped ${name} (PID ${pid}) on port ${port}`);
    } else {
      info(color('red', `${label.padEnd(9)} could not stop PID ${pid} — try running the terminal as administrator`));
    }
  }
}

info('');
info(killed ? color('green', 'Ports are free. Run `npm run dev` to start again.') : 'Nothing to stop.');
