import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { once } from 'node:events';

const calls = [];
let releaseStream = () => {};
let streamClosed = false;
const backend = createServer(async (req, res) => {
  let body = '';
  for await (const chunk of req) body += chunk;
  calls.push({ url: req.url, method: req.method, authorization: req.headers.authorization, cookie: req.headers.cookie, body });
  res.setHeader('Content-Type', 'application/json');
  if (req.url.endsWith('/runs/stream')) {
    streamClosed = false;
    res.on('close', () => { streamClosed = true; });
    res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
    res.setHeader('X-Accel-Buffering', 'no');
    res.write('event: run.started\ndata: {"version":1,"seq":1,"type":"run.started","session_id":"opaque/id","run_id":"smoke-stream","data":{"thinking":null}}\n\n');
    releaseStream = () => res.end('event: run.completed\ndata: {"version":1,"seq":2,"type":"run.completed","session_id":"opaque/id","run_id":"smoke-stream","data":{"status":"completed","answer":"stub only","warnings":[]}}\n\n');
    return;
  }
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
  for (const [method, path, body] of [
    ['GET', 'runtime'], ['GET', 'providers'], ['GET', 'models'],
    ['POST', 'model-logins', { provider: 'mock', api_key: 'mock-key-only' }],
    ['POST', 'model-logins/preview/confirm', { model: 'mock-model' }],
    ['PUT', 'runtime/model', { provider: 'mock', model: 'mock-model' }],
    ['PUT', 'runtime/thinking', { level: 'high' }],
  ]) {
    const result = await fetch(origin + '/api/omt/api/v1/' + path, {
      method, headers: { Origin: origin, 'Content-Type': 'application/json', Authorization: 'ignored', Cookie: 'ignored=value' },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    assert.equal(result.status, 200);
    await result.text();
    assert.equal(calls.at(-1).method, method);
    assert.equal(calls.at(-1).url, '/api/v1/' + path);
    assert.equal(calls.at(-1).body, body ? JSON.stringify(body) : '');
    assert.equal(calls.at(-1).authorization, undefined);
    assert.equal(calls.at(-1).cookie, undefined);
  }
  const streamUrl = origin + '/api/omt/api/v1/sessions/opaque%2Fid/runs/stream';
  const streamOptions = { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: '{"message":"isolated mock only"}' };
  const stream = await fetch(streamUrl, { ...streamOptions, signal: AbortSignal.timeout(10000) });
  assert.equal(stream.status, 200);
  assert.equal(stream.headers.get('x-accel-buffering'), 'no');
  const reader = stream.body.getReader();
  const firstChunk = await reader.read();
  assert.match(new TextDecoder().decode(firstChunk.value), /run.started/);
  // The backend has not sent a terminal or closed yet. Receiving this chunk
  // proves that the built proxy is not waiting for response.text().
  releaseStream();
  let remaining = '';
  while (true) { const chunk = await reader.read(); if (chunk.done) break; remaining += new TextDecoder().decode(chunk.value); }
  assert.match(remaining, /run.completed/);
  const aborter = new AbortController();
  const stopping = await fetch(streamUrl, { ...streamOptions, signal: aborter.signal });
  const stoppingReader = stopping.body.getReader();
  await stoppingReader.read();
  aborter.abort();
  await stoppingReader.cancel().catch(() => {});
  for (let index = 0; index < 100 && !streamClosed; index++) await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(streamClosed, true, 'Browser abort must close the upstream stream, not just hide the UI');
  assert.equal(calls.filter(call => call.url.endsWith('/runs/stream')).length, 2, 'Stream POST must not retry');
  console.log('PASS: built Next route → isolated HTTP stub; runtime/configuration GET/POST/PUT, SSE delivered before EOF, downstream abort closes upstream, encoded ID, no credentials forwarded, cross-origin rejection. No real backend called.');
} finally {
  frontend.kill('SIGTERM');
  if (frontend.exitCode === null) await once(frontend, 'exit');
  backend.closeAllConnections();
  await new Promise(resolve => backend.close(resolve));
}
