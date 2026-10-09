/*
 * journey-builder.js: record an auth flow as a Token Journey trace from JavaScript/TypeScript
 * (Node backends, gateways, Express/Fastify middleware, browser test harnesses).
 * Same model and the same defaults as the Python recorder in recorder/python. Zero dependencies.
 *
 *   const { Journey } = require('./journey-builder');
 *   const j = new Journey('Agent reads a ticket for Kim', { subtitle: 'RFC 8693 token exchange' })
 *     .actor('user', 'Kim (user)', { kind: 'user' })
 *     .actor('idp', 'Authorization server', { short: 'AS', kind: 'idp' })
 *     .actor('api', 'Ticket API', { short: 'API', kind: 'resource' })
 *     .message('user', 'idp', 'token request', { tone: 'info', token: 'grant' })
 *     .event('idp', 'mints token', { tone: 'ok', token: 'access token' })
 *     .message('user', 'api', 'GET /tickets/42', { tone: 'ok', detail: '+ token' })
 *     .allow('Ticket returned')
 *     .token('Access token', { raw: accessToken });   // signature redacted by default
 *   fs.writeFileSync('journey.json', j.stringify());
 */
'use strict';

const TONES = ['neutral', 'info', 'ok', 'deny'];
const KINDS = ['user', 'agent', 'gateway', 'idp', 'resource', 'service'];
const STATUSES = ['allow', 'deny', 'refused'];
const REDACTED_SIGNATURE = 'REDACTED-SIGNATURE';

function b64urlJson(seg) {
  const s = seg.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (seg.length % 4)) % 4);
  const txt = typeof Buffer !== 'undefined' ? Buffer.from(s, 'base64').toString('utf8') : decodeURIComponent(escape(atob(s)));
  return JSON.parse(txt);
}

/** Decode a compact JWT's header and payload WITHOUT verifying it. Returns null if not a JWT. */
function decodeJwt(raw) {
  if (typeof raw !== 'string') return null;
  const p = raw.split('.');
  if (p.length < 2) return null;
  try { return { header: b64urlJson(p[0]), payload: b64urlJson(p[1]) }; } catch (e) { return null; }
}

/** Replace a JWT's signature so it can't be replayed; opaque tokens are reduced to a prefix. */
function redactJwt(raw) {
  const p = typeof raw === 'string' ? raw.split('.') : [];
  if (p.length === 3 && decodeJwt(raw)) return `${p[0]}.${p[1]}.${REDACTED_SIGNATURE}`;
  return typeof raw === 'string' ? raw.slice(0, 6) + '...[opaque token redacted]' : raw;
}

function pick(obj, keys) {
  const out = {};
  keys.forEach(k => { if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== false) out[k] = obj[k]; });
  return out;
}

class Journey {
  constructor(title, { subtitle, tags } = {}) {
    this._d = { version: 1, title, actors: [], steps: [] };
    if (subtitle) this._d.subtitle = subtitle;
    if (tags) this._d.tags = [...tags];
    this._ids = new Set();
  }

  /** Declare a participant. Declaration order = left-to-right lane order. */
  actor(id, label, opts = {}) {
    if (!id) throw new Error('actor id is required');
    if (this._ids.has(id)) throw new Error(`actor "${id}" declared twice`);
    if (opts.kind && !KINDS.includes(opts.kind)) throw new Error(`actor "${id}": kind must be one of ${KINDS.join(', ')}`);
    this._d.actors.push({ id, label, ...pick(opts, ['short', 'kind', 'sublabel', 'color', 'description']) });
    this._ids.add(id);
    return this;
  }

  /** Narrative card: what happened, why it happened, why it matters. */
  static story(title, opts = {}) {
    if (opts.status && !['done', 'deny', 'skip'].includes(opts.status)) throw new Error('story status must be done, deny or skip');
    return { title, ...pick(opts, ['what', 'why', 'matters', 'status', 'actor']) };
  }

  _check(id, field) {
    if (!this._ids.has(id)) throw new Error(`step ${field} "${id}" is not a declared actor (declared: ${[...this._ids].join(', ')})`);
  }
  _push(base, label, opts) {
    if (!label) throw new Error('step label is required');
    if (opts.tone && !TONES.includes(opts.tone)) throw new Error(`tone must be one of ${TONES.join(', ')}`);
    this._d.steps.push({ ...base, label, ...pick(opts, ['tone', 'detail', 'token', 'symbol', 'note', 'story']), ...(opts.response ? { return: true } : {}) });
    return this;
  }

  /** An arrow between two actors. Set { response: true } for a dashed reply arrow. */
  message(from, to, label, opts = {}) {
    this._check(from, 'from'); this._check(to, 'to');
    if (from === to) throw new Error('a message needs two different actors; use event() for something at one actor');
    return this._push({ type: 'message', from, to }, label, opts);
  }

  /** Something that happens at one actor: minting, a policy decision, a failed check. */
  event(at, label, opts = {}) {
    this._check(at, 'at');
    return this._push({ type: 'event', at }, label, opts);
  }

  outcome(status, opts = {}) {
    if (!STATUSES.includes(status)) throw new Error(`outcome status must be one of ${STATUSES.join(', ')}`);
    this._d.outcome = { status, ...pick(opts, ['headline', 'detail', 'caption']) };
    return this;
  }
  allow(detail, opts = {}) { return this.outcome('allow', { detail, ...opts }); }
  /** No token was issued. */
  deny(detail, opts = {}) { return this.outcome('deny', { detail, ...opts }); }
  /** A token was issued but the resource rejected the call. */
  refused(detail, opts = {}) { return this.outcome('refused', { detail, ...opts }); }

  /** Attach a token card. JWT signatures are redacted unless { redact: false }. */
  token(label, { raw, claims, show, missing, note, redact = true } = {}) {
    if (raw === undefined && claims === undefined) throw new Error('token needs raw or claims');
    if (raw !== undefined && claims === undefined && !decodeJwt(raw)) throw new Error('raw is not a JWT; pass claims for opaque tokens');
    const t = { label, ...(raw !== undefined ? { raw: redact ? redactJwt(raw) : raw } : {}), ...pick({ claims, show, missing, note }, ['claims', 'show', 'missing', 'note']) };
    (this._d.tokens = this._d.tokens || []).push(t);
    return this;
  }

  link(label, href) {
    if (!/^https?:\/\//.test(href)) throw new Error('link href must be http(s)');
    (this._d.links = this._d.links || []).push({ label, href });
    return this;
  }

  toObject() {
    if (this._d.actors.length < 2) throw new Error('a journey needs at least two actors');
    if (!this._d.steps.length) throw new Error('a journey needs at least one step');
    return JSON.parse(JSON.stringify(this._d));
  }
  // Named stringify, not toJSON: a toJSON method would hijack JSON.stringify(journey).
  stringify(indent = 2) { return JSON.stringify(this.toObject(), null, indent); }
}

module.exports = { Journey, decodeJwt, redactJwt, TONES, KINDS };
