// node --test tests/   : validator, decoder, example files, and Python/JS recorder parity.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const TJ = require('../viewer/token-journey.js');
const { Journey, redactJwt } = require('../recorder/js/journey-builder.js');

const EX = path.join(__dirname, '..', 'examples', 'journeys');
const examples = JSON.parse(fs.readFileSync(path.join(EX, 'index.json'), 'utf8'));

test('every example journey is valid', () => {
  for (const it of examples) {
    const j = JSON.parse(fs.readFileSync(path.join(EX, it.file), 'utf8'));
    assert.deepStrictEqual(TJ.validate(j), [], it.file);
  }
});

test('validator reports precise errors', () => {
  const errs = TJ.validate({ version: 1, actors: [{ id: 'a', label: 'A' }, { id: 'a', label: 'B', kind: 'robot' }],
    steps: [{ type: 'message', from: 'a', to: 'zz', label: 'x', tone: 'green' }, { type: 'event', at: 'a' }], outcome: { status: 'maybe' } });
  const text = errs.join('\n');
  for (const want of ['duplicated', 'kind must be', 'not a declared actor', 'tone must be', '.label is required', 'outcome.status'])
    assert.ok(text.includes(want), 'missing: ' + want + '\n' + text);
  assert.deepStrictEqual(TJ.validate(null), ['journey must be an object']);
});

test('decodeJwt and scopesOf', () => {
  const raw = redactJwt('eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJraW0iLCJzY29wZSI6ImEgYiJ9.c2ln');
  assert.ok(raw.endsWith('.REDACTED-SIGNATURE'));
  assert.strictEqual(TJ.decodeJwt(raw).payload.sub, 'kim');
  assert.deepStrictEqual(TJ.scopesOf(TJ.decodeJwt(raw).payload), ['a', 'b']);
  assert.deepStrictEqual(TJ.scopesOf({ scp: ['x'] }), ['x']);
  assert.strictEqual(TJ.decodeJwt('garbage'), null);
});

test('JS recorder rejects mistakes and hijack-safe stringify', () => {
  const j = new Journey('t').actor('u', 'User').actor('s', 'Server');
  assert.throws(() => j.message('u', 'x', 'go'), /not a declared actor/);
  assert.throws(() => j.event('u', 'x', { tone: 'green' }), /tone must be/);
  assert.throws(() => j.link('x', 'javascript:alert(1)'), /http/);
  j.message('u', 's', 'go');
  assert.strictEqual(typeof JSON.parse(j.stringify()), 'object');
});

test('Python and JS recorders produce identical traces', () => {
  const py = `
import sys, json; sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..', 'recorder', 'python'))})
from token_journey import Journey
j = Journey("Parity", subtitle="s", tags=["a"])
j.actor("u", "User", kind="user", short="U").actor("idp", "IdP", kind="idp", sublabel="x.example")
j.message("u", "idp", "login", detail="d", tone="info", token="t", story=Journey.story("T", what="w", status="done"))
j.event("idp", "mint", tone="ok", token="tok").message("idp", "u", "ok", response=True)
j.allow("fine", caption="c").token("Access", raw="eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJraW0ifQ.c2ln", missing=["w"])
print(j.to_json())`;
  const fromPy = JSON.parse(execFileSync('python3', ['-c', py], { encoding: 'utf8' }));
  const fromJs = new Journey('Parity', { subtitle: 's', tags: ['a'] })
    .actor('u', 'User', { kind: 'user', short: 'U' }).actor('idp', 'IdP', { kind: 'idp', sublabel: 'x.example' })
    .message('u', 'idp', 'login', { detail: 'd', tone: 'info', token: 't', story: Journey.story('T', { what: 'w', status: 'done' }) })
    .event('idp', 'mint', { tone: 'ok', token: 'tok' }).message('idp', 'u', 'ok', { response: true })
    .allow('fine', { caption: 'c' }).token('Access', { raw: 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJraW0ifQ.c2ln', missing: ['w'] })
    .toObject();
  assert.deepStrictEqual(fromJs, fromPy);
});
