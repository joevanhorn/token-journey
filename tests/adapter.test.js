'use strict';
const test = require('node:test');
const assert = require('node:assert');
const TJ = require('../viewer/token-journey.js');
const { toJourney, classify } = require('../adapters/okta-xaa-lab.js');

const tok = { decoded: { sub: 'kim@example.com', aud: 'api://desk', iss: 'https://idp.example.com/oauth2/x', scopes: ['itsm.tickets.read'] } };
const cases = {
  allow:   { persona: 'kim', flow: [{ hop: 'agent', status: 'ok' }, { hop: 'adapter', status: 'ok' }, { hop: 'xaa', status: 'ok' }, { hop: 'app', status: 'ok' }], token: tok, request: { params: { name: 'desk__itsm.lookup_ticket' } } },
  deny:    { persona: 'frank', flow: [{ hop: 'agent', status: 'ok' }, { hop: 'adapter', status: 'ok' }, { hop: 'xaa', status: 'denied' }], denial: { status: 403, verbatim: 'Authentication failed for resource' } },
  refused: { persona: 'susan', flow: [{ hop: 'xaa', status: 'ok' }, { hop: 'app', status: 'denied' }], token: tok, denial: { status: 403, verbatim: 'missing required scope: crm.accounts.write' } },
  gateway: { persona: 'kim', flow: [{ hop: 'adapter', status: 'denied' }], denial: { verbatim: 'agent disabled' } },
};

test('classifies every lab outcome', () => {
  assert.strictEqual(classify(cases.allow), 'allow');
  assert.strictEqual(classify(cases.deny), 'deny');
  assert.strictEqual(classify(cases.refused), 'refused');
  assert.strictEqual(classify(cases.gateway), 'gateway-deny');
});

test('every converted journey is valid with the expected outcome', () => {
  const want = { allow: 'allow', deny: 'deny', refused: 'refused', gateway: 'deny' };
  for (const [k, r] of Object.entries(cases)) {
    const j = toJourney(r, { personaLabel: k, appName: 'VantageDesk' });
    assert.deepStrictEqual(TJ.validate(j), [], k);
    assert.strictEqual(j.outcome.status, want[k], k);
  }
  const ref = toJourney(cases.refused, { appName: 'VantageCRM' });
  assert.deepStrictEqual(ref.tokens[0].missing, ['crm.accounts.write']);
});
