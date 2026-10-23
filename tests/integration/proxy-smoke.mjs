import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { once } from 'node:events';

const calls = [];
const backend = createServer(async (req, res) => {
  let body = '';
  for await (const chunk of req) body += chunk;
  calls.push({ url: req.url, method: req.method, authorization: req.headers.authorization, cookie: req.headers.cookie, body });
  res.setHeader('Content-Type', 'application/json');
  if (req.url === '/health') res.end('{"status":"ok"}');
  else if (req.url.endsWith('/runs')) res.end(JSON.stringify({ session_id: 'opaque/id', run_id: 'smoke-run', status: 'completed', answer: 'stub only', warnings: [] }));
  else res.end('[]');
});
backend.listen(0, '127.0.0.1');
await once(backend, 'listening');
const backendPort = backend.address().port;
const probe = createServer();
probe.listen(0, '127.0.0.1');
await once(probe, 'listening');
const frontendPort = probe.address().port;
await new Promise(resolve => probe.close(resolve));
const frontend = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', String(frontendPort)], {
  cwd: process.cwd(),
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1', OMT_BACKEND_URL: `http://127.0.0.1:${backendPort}` },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let logs = '';
frontend.stdout.on('data', chunk => { logs += chunk; });
frontend.stderr.on('data', chunk => { logs += chunk; });
const origin = `http://127.0.0.1:${frontendPort}`;
try {
  let ready = false;
  for (let index = 0; index < 60; index++) {
    if (frontend.exitCode !== null) throw new Error(logs);
    try { if ((await fetch(origin)).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, logs);
  assert.deepEqual(await (await fetch(origin + '/api/omt/health')).json(), { status: 'ok' });
  const response = await fetch(origin + '/api/omt/api/v1/sessions/opaque%2Fid/runs', {
    method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json', Cookie: 'do-not-forward=secret' },
    body: JSON.stringify({ message: 'local mock only' }),
  });
  assert.equal(response.status, 200, await response.clone().text());
  assert.equal((await response.json()).answer, 'stub only');
  assert.deepEqual(calls[1], { url: '/api/v1/sessions/opaque%2Fid/runs', method: 'POST', authorization: undefined, cookie: undefined, body: '{"message":"local mock only"}' });
  assert.equal((await fetch(origin + '/api/omt/api/v1/sessions', { method: 'POST', headers: { Origin: 'https://foreign.invalid', 'Content-Type': 'application/json' }, body: '{}' })).status, 403);
  assert.equal(calls.length, 2);
  assert.equal((await fetch(origin + '/api/omt/api/v1/sessions')).status, 200);
  assert.equal((await fetch(origin + '/api/omt/api/v1/sessions', {
    method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: '{}',
  })).status, 200);
  assert.equal((await fetch(origin + '/api/omt/api/v1/sessions/opaque%2Fid/messages')).status, 200);
  assert.equal((await fetch(origin + '/api/omt/api/v1/sessions', {
    headers: { Authorization: 'Bearer ignored-test-value', Cookie: 'do-not-forward=secret' },
  })).status, 200);
  assert.equal(calls.length, 6);
  for (const call of calls) {
    assert.equal(call.authorization, undefined);
    assert.equal(call.cookie, undefined);
  }
  assert.deepEqual(calls.slice(2).map(({ url, method, body }) => ({ url, method, body })), [
    { url: '/api/v1/sessions', method: 'GET', body: '' },
    { url: '/api/v1/sessions', method: 'POST', body: '{}' },
    { url: '/api/v1/sessions/opaque%2Fid/messages', method: 'GET', body: '' },
    { url: '/api/v1/sessions', method: 'GET', body: '' },
  ]);
  console.log('PASS: built Next route → isolated local HTTP stub; all endpoints without auth, encoded ID, JSON, no Authorization/Cookie forwarding, cross-origin rejection. No real backend called.');
} finally {
  frontend.kill('SIGTERM');
  if (frontend.exitCode === null) await once(frontend, 'exit');
  backend.closeAllConnections();
  await new Promise(resolve => backend.close(resolve));
}
