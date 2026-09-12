#!/usr/bin/env node
/**
 * Runs every check in the project.
 *
 *   npm test
 *
 * The offline suites need nothing running. The API and contract suites need a
 * live backend, so they are skipped with a note if port 8000 is quiet.
 */

import { spawnSync } from 'node:child_process';
import { CLIENT, IS_WIN, ROOT, SERVER, color, fail, info, ok, portBusy, venvPython, warn } from './lib.mjs';

const results = [];

function suite(name, command, args, cwd) {
  info(color('cyan', `\n▸ ${name}`));
  const res = spawnSync(command, args, { cwd, stdio: 'inherit', shell: IS_WIN });
  const passed = res.status === 0;
  results.push({ name, passed });
  return passed;
}

suite('Adaptive engine (offline)', venvPython(), ['scripts/test_engine.py'], SERVER);
suite('Code sandbox (needs Docker)', venvPython(), ['scripts/test_sandbox.py'], SERVER);

if (await portBusy(8000)) {
  suite('Backend API', venvPython(), ['scripts/smoke_test.py'], SERVER);
  suite('Backend features', venvPython(), ['scripts/test_features.py'], SERVER);
  suite('Frontend/backend contract', 'node', ['scripts/contract-test.mjs'], CLIENT);
} else {
  warn('\n▸ Skipped the API suites — nothing is listening on port 8000.');
  warn('  Start the backend first:  npm run dev:api');
}

suite('Frontend build', IS_WIN ? 'npm.cmd' : 'npm', ['run', 'build'], CLIENT);

const failed = results.filter((r) => !r.passed);
info('');
for (const r of results) info(`${r.passed ? color('green', '  PASS') : color('red', '  FAIL')}  ${r.name}`);
info('');
if (failed.length) {
  fail(`${failed.length} of ${results.length} suites failed.`);
  process.exit(1);
}
ok(`All ${results.length} suites passed.`);
