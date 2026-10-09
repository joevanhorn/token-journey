/*
 * okta-xaa-lab.js: adapter: turn the Okta for AI Agents lab toolkit's backend responses into
 * Token Journey traces.
 *
 * WHY THIS FILE EXISTS
 * The viewer in this repo was extracted from that lab. In the lab, the flow knowledge (which
 * actors, which steps, what each outcome means) lived inside the renderer. Here it lives in an
 * adapter instead, which is the pattern to copy when you retrofit an app you already have:
 * keep your backend's native response shape, and write one small function that maps it to a
 * journey. Your renderer never changes.
 *
 * INPUT: the lab backend's response to an agent action, roughly:
 *   {
 *     persona: 'kim',
 *     flow: [ { hop: 'agent'|'adapter'|'xaa'|'app', status: 'ok'|'denied'|'skipped', note? } ],
 *     token: { raw, decoded: { sub, aud, iss, scopes } } | undefined,   // the minted resource token
 *     denial: { status, verbatim } | undefined,                         // the refusal, verbatim
 *     request: { params: { name: 'desk__itsm.lookup_ticket' } },        // the tool that was called
 *     systemLog: { deepLink } | undefined
 *   }
 * The four hops are the lab's model of an agentic call: the agent asks, the adapter (an MCP
 * gateway) brokers, Okta performs the Cross App Access exchange (ID-JAG), the app answers.
 *
 * OUTPUT: a version-1 journey (docs/journey-format.md).
 *
 * Usage (browser or Node):
 *   const journey = OktaXaaLab.toJourney(response, { personaLabel: 'Kim Liu', appName: 'VantageDesk' });
 *   TokenJourney.render(el, journey);
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('../recorder/js/journey-builder.js'));
  else root.OktaXaaLab = factory({ Journey: root.JourneyBuilder && root.JourneyBuilder.Journey });
})(typeof self !== 'undefined' ? self : this, function (builder) {
  'use strict';
  var Journey = builder.Journey;

  function hop(flow, name) {
    var h = (flow || []).filter(function (x) { return x.hop === name; })[0];
    return h ? h.status : 'skipped';
  }
  // The lab's resources answer 403 with "missing required scope: X"; pull X out for the token card.
  function missingScope(verbatim) {
    var m = /missing (?:required )?scopes?:?\s*([A-Za-z0-9_.:*\/-]+)/i.exec(verbatim || '');
    return m ? m[1] : null;
  }

  /**
   * Classify the response into one of the three outcomes every journey ends in.
   *   allow   : the exchange minted a token and the app accepted it
   *   deny    : no token (the gateway refused, or Okta matched no policy rule)
   *   refused : a token was minted, but narrower than the user, so the app returned 403
   */
  function classify(r) {
    var xaa = hop(r.flow, 'xaa'), app = hop(r.flow, 'app'), adapter = hop(r.flow, 'adapter');
    if (adapter === 'denied') return 'gateway-deny';
    if (xaa === 'ok' && app === 'denied') return 'refused';
    if (r.denial || xaa === 'denied' || app === 'denied') return 'deny';
    return 'allow';
  }

  function toJourney(r, opts) {
    opts = opts || {};
    var who = opts.personaLabel || r.persona || 'the user';
    var first = String(who).split(' ')[0];
    var app = opts.appName || 'the app';
    var tool = (r.request && ((r.request.params && r.request.params.name) || r.request.tool)) || 'tools/call';
    var shortTool = tool.split('__').pop();
    var outcome = classify(r);
    var S = Journey.story;

    var j = new Journey('Agent calls ' + shortTool + ' for ' + who, { subtitle: 'Okta Cross App Access (ID-JAG) through the MCP bridge', tags: ['agentic', 'XAA'] })
      .actor('user', who, { short: 'USR', kind: 'user' })
      .actor('agent', 'Agent', { short: 'AGT', kind: 'agent' })
      .actor('bridge', 'MCP bridge', { short: 'BRG', kind: 'gateway' })
      .actor('okta', 'Okta', { short: 'OKTA', kind: 'idp' })
      .actor('app', app, { short: 'RES', kind: 'resource' });

    j.message('user', 'agent', 'ask agent', { story: S('You asked the agent', {
      what: first + ' asked the agent to call ' + shortTool + '.',
      why: 'The agent has no identity of its own to act with. It works strictly on ' + first + "'s behalf.",
      matters: "Every call traces back to a real person, and inherits that person's limits." }) });
    j.message('agent', 'bridge', 'tools/call', { detail: shortTool, tone: 'info' });

    if (outcome === 'gateway-deny') {
      j.event('bridge', 'refused', { tone: 'deny', story: S('The bridge refused the request', { status: 'deny',
        what: 'The bridge stopped the call before asking Okta for a token.', why: (r.denial && r.denial.verbatim) || 'The bridge rejected the request.',
        matters: 'A governed agent fails closed.' }) });
      j.deny((r.denial && r.denial.verbatim) || 'The bridge refused the call.', { caption: 'bridge refused · no token requested' });
      return j.toObject();
    }

    j.message('bridge', 'okta', 'ID-JAG request', { detail: 'grant=jwt-bearer', tone: 'info', token: 'agent ⊕ user', story: S('The bridge brokered it to Okta', {
      what: "The bridge presented the agent's request to Okta and asked for a token through the ID-JAG exchange.",
      why: "An agent can't mint its own credentials. Only Okta issues tokens, and only after checking policy.",
      matters: 'The exchange is the checkpoint: every agent action goes through Okta before it touches a resource.' }) });
    j.event('okta', 'mints ID-JAG', { tone: 'info', token: 'ID-JAG' });
    j.message('bridge', 'okta', 'token exchange', { detail: 'ID-JAG → token', tone: 'info' });

    if (outcome === 'deny') {
      j.event('okta', 'no matching rule', { tone: 'deny', token: 'DENIED', story: S('Okta refused: no token', { status: 'deny',
        what: 'No policy rule matched ' + who + ' at the exchange, so Okta minted no token.',
        why: first + " doesn't have this access, and the agent only ever borrows " + first + "'s rights.",
        matters: "The agent can't do what the user can't." }) });
      j.message('okta', 'bridge', 'no token', { tone: 'deny', response: true });
      j.deny(((r.denial && r.denial.verbatim) || 'No scoped token was minted at the exchange.') + " The agent can't do what the user can't.",
        { headline: '✕ BLOCKED: NO TOKEN', caption: 'no rule matched at the exchange · no token · ' + app + ' never reached' });
    } else {
      var refused = outcome === 'refused';
      var miss = refused ? missingScope(r.denial && r.denial.verbatim) : null;
      j.event('okta', refused ? 'narrows scopes' : 'mints token', { tone: 'ok', token: 'scoped token', story: S(refused ? 'Okta minted a narrow token' : 'Okta minted a scoped token', {
        what: refused ? "Okta issued a token, but the agent's connection is limited below " + who + ', so it left out ' + (miss || 'the scope this call needs') + '.'
                      : 'Okta checked ' + who + "'s policy and issued a scoped token.",
        why: 'The token is the intersection of what ' + first + ' may do and what this agent may do.',
        matters: refused ? "The limit is the token itself." : "The agent borrows your keys, bounded to your rights." }) });
      j.message('bridge', 'app', 'call ' + shortTool, { detail: '+ token', tone: refused ? 'info' : 'ok', token: 'access token' });
      if (refused) {
        j.event('app', '403', { tone: 'deny', token: '403', story: S(app + ' refused the call (403)', { status: 'deny',
          what: app + ' found the token missing ' + (miss || 'the required scope') + ' and refused.',
          why: 'The app enforces scope on every call.', matters: 'The limit is a real, machine-checked refusal.' }) });
        j.refused((r.denial && r.denial.verbatim) || 'The app refused the narrowed token.', { headline: '✕ BLOCKED: AGENT LIMITED', caption: 'token minted but narrower than ' + who + ' · ' + app + ' refused (403)' });
      } else {
        j.event('app', '200 OK', { tone: 'ok', token: '200 OK', story: S(app + ' honored the call', {
          what: app + ' accepted the scoped token and returned 200.', why: 'The token carried exactly the scope this call required.',
          matters: 'Access was proven for this one call, not assumed from a standing login.' }) });
        j.allow('Okta authorized ' + who + ' and minted a token bounded to what they may do.', { headline: '✓ USABLE: TOKEN ISSUED', caption: 'scoped token minted · ' + app + ' returned 200' });
      }
      if (r.token && (r.token.raw || r.token.decoded)) {
        var d = r.token.decoded || {};
        j.token('Access token', r.token.raw ? { raw: r.token.raw, missing: miss ? [miss] : undefined }
          : { claims: { sub: d.sub, aud: d.aud, iss: d.iss, scp: d.scopes }, missing: miss ? [miss] : undefined });
      }
    }
    if (r.systemLog && r.systemLog.deepLink) j.link('Open in Okta System Log', r.systemLog.deepLink);
    return j.toObject();
  }

  return { toJourney: toJourney, classify: classify };
});
