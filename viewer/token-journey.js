/*!
 * token-journey.js: render an auth "token journey" as a plain-language story and an animated
 * sequence diagram. Zero dependencies. Works as a <script> tag (window.TokenJourney), as a
 * CommonJS module, or bundled.
 *
 * The viewer knows NOTHING about any particular identity provider or protocol. It plays a
 * Journey trace: a JSON document listing the actors, the ordered steps (messages between actors
 * and events at one actor), the tokens involved, and the outcome. Producing that trace is the
 * job of your code (see /recorder) or a hand-written file (see /examples/journeys).
 * Format reference: docs/journey-format.md and schema/journey.schema.json.
 *
 * Public API
 *   TokenJourney.render(container, journey, options) -> controller
 *       options.view       'technical' | 'narrative'  (default 'technical')
 *       options.controls   show the Narrative/Technical toggle + replay button (default true)
 *       options.animate    play the build-out; false paints the final state at once (default true)
 *       options.speed      animation speed multiplier, 2 = twice as fast (default 1)
 *       options.motion     'auto' honors prefers-reduced-motion; 'always' animates regardless (default 'auto')
 *       options.theme      'auto' | 'light' | 'dark' (default 'auto')
 *       options.tokens     'technical' shows token cards only in Technical view; 'always' in both
 *       options.onDone     called when the build-out finishes
 *     controller: { setView(v), replay(), destroy(), journey }
 *   TokenJourney.validate(journey) -> string[]   empty array means valid
 *   TokenJourney.decodeJwt(raw)    -> { header, payload } | null   (decodes, never verifies)
 *
 * Security notes for embedders
 *   - Every string from the trace is written with textContent, never innerHTML, so a hostile
 *     trace cannot inject markup or script.
 *   - Links are only rendered for http: and https: URLs.
 *   - decodeJwt does NOT verify signatures. The viewer is a teaching and debugging aid; never
 *     use it to make trust decisions, and don't publish traces containing live tokens
 *     (the recorders redact signatures by default).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TokenJourney = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';
  var TONES = ['neutral', 'info', 'ok', 'deny'];
  var KINDS = ['user', 'agent', 'gateway', 'idp', 'resource', 'service'];
  var STATUSES = ['allow', 'deny', 'refused'];

  // ── tiny DOM helpers ───────────────────────────────────────────────
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'class') n.className = attrs[k];
      else if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function svgEl(tag, attrs, parent) {
    var n = document.createElementNS(SVGNS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function safeHref(u) { return /^https?:\/\//i.test(String(u || '')) ? String(u) : null; }

  // ── JWT decode (no verification, by design) ───────────────────────
  function b64urlDecode(s) {
    s = String(s).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = typeof atob === 'function' ? atob(s) : Buffer.from(s, 'base64').toString('binary');
    try { return decodeURIComponent(bin.split('').map(function (c) { return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2); }).join('')); }
    catch (e) { return bin; }
  }
  function decodeJwt(raw) {
    if (typeof raw !== 'string') return null;
    var parts = raw.split('.');
    if (parts.length < 2) return null;
    try { return { header: JSON.parse(b64urlDecode(parts[0])), payload: JSON.parse(b64urlDecode(parts[1])) }; }
    catch (e) { return null; }
  }
  // Scopes appear as `scp` (array, Okta and others) or `scope` (space-delimited string, RFC 9068).
  function scopesOf(claims) {
    if (!claims) return [];
    if (Array.isArray(claims.scp)) return claims.scp.map(String);
    if (typeof claims.scp === 'string') return claims.scp.split(/\s+/).filter(Boolean);
    if (typeof claims.scope === 'string') return claims.scope.split(/\s+/).filter(Boolean);
    if (Array.isArray(claims.scope)) return claims.scope.map(String);
    return [];
  }

  // ── validation: precise, human-readable errors for trace authors ──
  function validate(j) {
    var errs = [];
    if (!j || typeof j !== 'object') return ['journey must be an object'];
    if (j.version !== 1) errs.push('version must be 1');
    if (!Array.isArray(j.actors) || j.actors.length < 2) errs.push('actors must be an array with at least 2 actors');
    if (!Array.isArray(j.steps) || !j.steps.length) errs.push('steps must be a non-empty array');
    var ids = {};
    (j.actors || []).forEach(function (a, i) {
      if (!a || typeof a.id !== 'string' || !a.id) errs.push('actors[' + i + '].id is required');
      else if (ids[a.id]) errs.push('actors[' + i + '].id "' + a.id + '" is duplicated');
      else ids[a.id] = true;
      if (a && typeof a.label !== 'string') errs.push('actors[' + i + '].label is required');
      if (a && a.kind && KINDS.indexOf(a.kind) < 0) errs.push('actors[' + i + '].kind must be one of ' + KINDS.join(', '));
    });
    (j.steps || []).forEach(function (s, i) {
      var p = 'steps[' + i + ']';
      if (!s || (s.type !== 'message' && s.type !== 'event')) { errs.push(p + '.type must be "message" or "event"'); return; }
      if (s.type === 'message') {
        if (!ids[s.from]) errs.push(p + '.from "' + s.from + '" is not a declared actor');
        if (!ids[s.to]) errs.push(p + '.to "' + s.to + '" is not a declared actor');
        if (s.from === s.to) errs.push(p + ': a message needs two different actors (use an "event" for something that happens at one actor)');
      } else if (!ids[s.at]) errs.push(p + '.at "' + s.at + '" is not a declared actor');
      if (typeof s.label !== 'string' || !s.label) errs.push(p + '.label is required');
      if (s.tone && TONES.indexOf(s.tone) < 0) errs.push(p + '.tone must be one of ' + TONES.join(', '));
      if (s.story && typeof s.story.title !== 'string') errs.push(p + '.story.title is required when story is present');
    });
    if (j.outcome) {
      if (STATUSES.indexOf(j.outcome.status) < 0) errs.push('outcome.status must be one of ' + STATUSES.join(', '));
    }
    (j.tokens || []).forEach(function (t, i) {
      if (!t || (!t.raw && !t.claims)) errs.push('tokens[' + i + '] needs raw or claims');
    });
    return errs;
  }

  // ── narrative: one card per step that carries a `story` ───────────
  function storyCards(j, actorById) {
    var cards = [];
    j.steps.forEach(function (s) {
      if (!s.story) return;
      var actorId = s.story.actor || (s.type === 'event' ? s.at : s.from);
      cards.push({ actor: actorById[actorId] || { id: actorId, label: actorId }, story: s.story,
        status: s.story.status || (s.tone === 'deny' ? 'deny' : 'done') });
    });
    return cards;
  }

  var DEFAULT_HEADLINE = { allow: '✓ ALLOWED', deny: '✕ DENIED: NO TOKEN', refused: '✕ REFUSED BY RESOURCE' };
  var STATUS_TAG = { allow: 'authorized', deny: 'denied', refused: 'refused' };

  // ── main render ────────────────────────────────────────────────────
  function render(container, journey, options) {
    if (!container) throw new Error('TokenJourney.render: container is required');
    var opt = Object.assign({ view: 'technical', controls: true, animate: true, speed: 1, motion: 'auto', theme: 'auto', tokens: 'technical' }, options || {});
    var seq = 0;           // bumped on every (re)draw; stale timers check it and bail
    var view = opt.view === 'narrative' ? 'narrative' : 'technical';

    clear(container);
    var rootEl = el('div', { class: 'tj', 'data-view': view, 'data-motion': opt.motion, 'data-tokens': opt.tokens });
    if (opt.theme === 'light' || opt.theme === 'dark') rootEl.setAttribute('data-theme', opt.theme);
    container.appendChild(rootEl);

    var errs = validate(journey);
    if (errs.length) {
      rootEl.appendChild(el('div', { class: 'tj-error', text: 'Invalid journey:\n- ' + errs.join('\n- ') }));
      return { setView: function () {}, replay: function () {}, destroy: function () { clear(container); }, journey: journey, errors: errs };
    }

    var actorById = {};
    journey.actors.forEach(function (a) { actorById[a.id] = a; });
    var outcome = journey.outcome || null;

    // header
    var statusEl = el('div', { class: 'tj-status', text: 'running…' });
    var hdTxt = el('div', { class: 'tj-hd-txt' }, [
      el('h4', { class: 'tj-title', text: journey.title || 'Token journey' }),
      journey.subtitle ? el('p', { class: 'tj-sub', text: journey.subtitle }) : null
    ]);
    if (journey.tags && journey.tags.length) {
      hdTxt.appendChild(el('div', { class: 'tj-tags' }, journey.tags.map(function (t) { return el('span', { class: 'tj-tag', text: String(t) }); })));
    }
    rootEl.appendChild(el('div', { class: 'tj-hd' }, [hdTxt, statusEl]));

    var btnN, btnT;
    if (opt.controls) {
      btnN = el('button', { type: 'button', text: 'Narrative' });
      btnT = el('button', { type: 'button', text: 'Technical' });
      var replayBtn = el('button', { type: 'button', class: 'tj-replay', text: '↻ replay', 'aria-label': 'Replay the journey' });
      btnN.addEventListener('click', function () { setView('narrative'); });
      btnT.addEventListener('click', function () { setView('technical'); });
      replayBtn.addEventListener('click', function () { draw(); });
      rootEl.appendChild(el('div', {}, [el('div', { class: 'tj-views', role: 'group', 'aria-label': 'Journey view' }, [btnN, btnT]), replayBtn]));
    }

    var stage = el('div', { class: 'tj-stage' });
    var verdict = el('div', { class: 'tj-verdict', role: 'status' });
    var tokensEl = el('div', { class: 'tj-tokens' });
    var linksEl = el('div', { class: 'tj-links' });
    rootEl.appendChild(stage); rootEl.appendChild(verdict); rootEl.appendChild(tokensEl); rootEl.appendChild(linksEl);

    function reducedMotion() {
      if (opt.motion === 'always') return false;
      return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    function timing(ms) { return (!opt.animate || reducedMotion()) ? 0 : ms / Math.max(0.1, opt.speed || 1); }
    function wait(ms, my) {
      return new Promise(function (res, rej) {
        var d = timing(ms);
        var go = function () { if (my !== seq) rej('cancel'); else res(); };
        if (d <= 0) go(); else setTimeout(go, d);
      });
    }

    function syncControls() {
      rootEl.setAttribute('data-view', view);
      if (btnN) { btnN.setAttribute('aria-pressed', String(view === 'narrative')); btnT.setAttribute('aria-pressed', String(view === 'technical')); }
    }
    function setView(v) { view = v === 'narrative' ? 'narrative' : 'technical'; syncControls(); draw(); }

    function draw() {
      var my = ++seq;
      syncControls();
      rootEl.classList.toggle('tj-instant', timing(1) === 0);
      statusEl.className = 'tj-status'; statusEl.textContent = 'running…';
      verdict.className = 'tj-verdict'; clear(verdict);
      tokensEl.className = 'tj-tokens'; clear(tokensEl); clear(linksEl);
      clear(stage);
      var run = view === 'narrative' ? playNarrative(my) : playSequence(my);
      run.then(function () { if (my === seq) finish(); }, function (e) { if (e !== 'cancel') throw e; });
    }

    function finish() {
      if (outcome) {
        var ok = outcome.status === 'allow';
        statusEl.className = 'tj-status ' + (ok ? 'ok' : 'no');
        statusEl.textContent = STATUS_TAG[outcome.status];
        verdict.className = 'tj-verdict show ' + (ok ? 'ok' : 'no');
        verdict.appendChild(el('div', { class: 'tj-vh', text: outcome.headline || DEFAULT_HEADLINE[outcome.status] }));
        if (outcome.detail) verdict.appendChild(el('div', { class: 'tj-vd', text: outcome.detail }));
      } else { statusEl.textContent = 'complete'; }
      renderTokens();
      (journey.links || []).forEach(function (l) {
        var href = safeHref(l.href);
        if (href) linksEl.appendChild(el('a', { class: 'tj-link', href: href, target: '_blank', rel: 'noopener noreferrer', text: '↗ ' + (l.label || href) }));
      });
      if (typeof opt.onDone === 'function') opt.onDone();
    }

    function renderTokens() {
      var toks = journey.tokens || [];
      if (!toks.length) {
        if (outcome && outcome.status === 'deny') {
          tokensEl.className = 'tj-tokens show';
          tokensEl.appendChild(el('div', { class: 'tj-token denied' }, [
            el('div', { class: 'tj-th' }, [el('span', { class: 'key', text: '✕' }), document.createTextNode('No token issued')]),
            el('div', { class: 'tj-empty', text: 'The authorization server minted nothing, so there is nothing to present.' })
          ]));
        }
        return;
      }
      tokensEl.className = 'tj-tokens show';
      toks.forEach(function (t) {
        var decoded = t.raw ? decodeJwt(t.raw) : null;
        var claims = t.claims || (decoded && decoded.payload) || {};
        var show = t.show || ['sub', 'aud', 'iss', 'scope', 'act', 'exp'];
        var card = el('div', { class: 'tj-token' });
        card.appendChild(el('div', { class: 'tj-th' }, [
          el('span', { class: 'key', text: '🔑' }),
          document.createTextNode(t.label || 'Token'),
          el('span', { class: 'aud', text: Array.isArray(claims.aud) ? claims.aud.join(', ') : (claims.aud || '') })
        ]));
        var grid = el('div', { class: 'tj-claims' });
        show.forEach(function (k) {
          var v;
          if (k === 'scope') {
            var sc = scopesOf(claims), miss = t.missing || [];
            if (!sc.length && !miss.length) return;
            var box = el('span', { class: 'tj-cv tj-scopes' });
            sc.forEach(function (s) { box.appendChild(el('span', { class: 'tj-scope', text: s })); });
            miss.forEach(function (s) { box.appendChild(el('span', { class: 'tj-scope miss', text: s, title: 'not granted' })); });
            grid.appendChild(el('span', { class: 'tj-ck', text: claims.scp ? 'scp' : 'scope' })); grid.appendChild(box);
            return;
          }
          if (!(k in claims)) return;
          v = claims[k];
          if (k === 'act' && v && typeof v === 'object') v = 'sub=' + v.sub + (v.act ? ' (nested act)' : '');   // RFC 8693 actor claim
          else if ((k === 'exp' || k === 'iat' || k === 'nbf') && typeof v === 'number') v = new Date(v * 1000).toISOString().replace('.000', '');
          else if (typeof v === 'object') v = JSON.stringify(v);
          grid.appendChild(el('span', { class: 'tj-ck', text: k }));
          grid.appendChild(el('span', { class: 'tj-cv', text: String(v) }));
        });
        card.appendChild(grid);
        if (t.note) card.appendChild(el('div', { class: 'tj-tnote', text: t.note }));
        if (t.raw && typeof navigator !== 'undefined' && navigator.clipboard) {
          var cp = el('button', { type: 'button', class: 'tj-copy', text: '⧉ Copy token' });
          cp.addEventListener('click', function () {
            navigator.clipboard.writeText(t.raw).then(function () { cp.textContent = '✓ Copied'; setTimeout(function () { cp.textContent = '⧉ Copy token'; }, 1400); });
          });
          card.appendChild(cp);
        }
        tokensEl.appendChild(card);
      });
    }

    // ── Narrative ────────────────────────────────────────────────────
    function playNarrative(my) {
      var cards = storyCards(journey, actorById).map(function (c) {
        var a = c.actor;
        var card = el('div', { class: 'tj-narr ' + c.status + (a.kind ? ' tj-k-' + a.kind : ' tj-k-service') });
        if (a.color) card.style.setProperty('--tj-act', a.color);
        var glyph = c.status === 'deny' ? '✗' : c.status === 'skip' ? '◦' : '✓';
        card.appendChild(el('div', { class: 'tj-narr-hd' }, [
          el('span', { class: 'tj-chip', text: a.label }), el('span', { class: 'tj-narr-ttl', text: c.story.title }), el('span', { class: 'tj-narr-st', text: glyph })
        ]));
        [['what', 'What', 'w-what'], ['why', 'Why', 'w-why'], ['matters', 'Why it matters', 'w-matters']].forEach(function (f) {
          if (c.story[f[0]]) card.appendChild(el('div', { class: 'tj-line ' + f[2] }, [el('span', { class: 'tj-k', text: f[1] }), document.createTextNode(c.story[f[0]])]));
        });
        stage.appendChild(card);
        return card;
      });
      if (!cards.length) stage.appendChild(el('p', { class: 'tj-sub', text: 'This journey has no narrative steps. Switch to Technical, or add a "story" to its steps.' }));
      var i = 0;
      function next() {
        if (i >= cards.length) return Promise.resolve();
        cards[i++].classList.add('in');
        return wait(520, my).then(next);
      }
      return Promise.resolve().then(next);
    }

    // ── Technical: the sequence diagram ──────────────────────────────
    function playSequence(my) {
      var actors = journey.actors, steps = journey.steps;
      var col = {}; actors.forEach(function (a, i) { col[a.id] = i; });
      var touched = {};
      steps.forEach(function (s) { if (s.type === 'message') { touched[s.from] = touched[s.to] = true; } else touched[s.at] = true; });

      var wrap = el('div', { class: 'tj-seq' });
      var diag = el('div', { class: 'tj-diagram' });
      var svg = svgEl('svg', { class: 'tj-svg', role: 'img', 'aria-label': 'Sequence diagram: ' + (journey.title || 'token journey') });
      diag.appendChild(svg);
      var pill = el('div', { class: 'tj-pill', 'aria-hidden': 'true' }, [el('span', { class: 'dot' })]);
      var pillTx = el('span'); pill.appendChild(pillTx); diag.appendChild(pill);
      wrap.appendChild(diag);
      var foot = el('div', { class: 'tj-foot' });
      wrap.appendChild(foot);
      stage.appendChild(wrap);

      // Geometry. viewBox units equal CSS px so the HTML pill can be positioned in the same space.
      // Lanes get at least MIN_GAP px; on narrow containers the diagram scrolls horizontally rather
      // than squeezing labels together.
      var MIN_GAP = 104;
      var avail = Math.max(260, stage.clientWidth || rootEl.clientWidth || 520);
      // Lane caps size to the wider of their two lines (mono cap text ~7px/char, sans sublabel ~5.4px/char).
      var capW = {};
      actors.forEach(function (a) {
        capW[a.id] = Math.max(46, (a.short || a.label).length * 7 + 16, a.sublabel ? a.sublabel.length * 5.4 + 14 : 0);
      });
      var widest = Math.max.apply(null, actors.map(function (a) { return capW[a.id]; }));
      var PADX = Math.max(44, widest / 2 + 6);
      var gap = Math.max(MIN_GAP, (avail - PADX * 2) / Math.max(1, actors.length - 1));
      var W = PADX * 2 + gap * (actors.length - 1);
      var hasSub = actors.some(function (a) { return a.sublabel; });
      var CAPY = 6, CAPH = hasSub ? 34 : 24, LLTOP = CAPY + CAPH, Y0 = LLTOP + 34, STEP = 48;
      var H = Y0 + (steps.length - 1) * STEP + 34;
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
      svg.setAttribute('width', W); svg.setAttribute('height', H);
      var X = function (id) { return PADX + col[id] * gap; };
      var Y = function (r) { return Y0 + r * STEP; };

      actors.forEach(function (a) {
        var x = X(a.id), on = !!touched[a.id];
        var g = svgEl('g', { class: a.kind ? 'tj-k-' + a.kind : 'tj-k-service' }, svg);
        if (a.color) g.style.setProperty('--tj-act', a.color);
        svgEl('line', { class: 'tj-ll' + (on ? '' : ' dim'), x1: x, y1: LLTOP, x2: x, y2: H - 8 }, g);
        var cw = Math.min(gap - 8, capW[a.id]);
        svgEl('rect', { class: 'tj-cap' + (on ? ' act' : ''), x: x - cw / 2, y: CAPY, width: cw, height: CAPH, rx: 7 }, g);
        svgEl('text', { class: 'tj-captx' + (on ? ' act' : ''), x: x, y: CAPY + (hasSub ? 14 : CAPH / 2 + 3.5) }, g).textContent = a.short || a.label;
        if (a.sublabel) svgEl('text', { class: 'tj-capsub', x: x, y: CAPY + 27 }, g).textContent = a.sublabel;
        var t = svgEl('title', {}, g); t.textContent = a.label + (a.description ? ': ' + a.description : '');
      });

      // pill
      function pillTo(x, y, instant) {
        if (instant) { pill.style.transition = 'none'; }
        pill.style.transform = 'translate(' + x + 'px,' + y + 'px) translate(-50%,-50%)';
        if (instant) { void pill.offsetWidth; pill.style.transition = ''; }
      }
      function pillShow(text, tone) {
        pillTx.textContent = text;
        pill.classList.remove('ok', 'deny', 'bump');
        if (tone === 'ok' || tone === 'deny') pill.classList.add(tone);
        pill.classList.add('show');
        if (timing(1) > 0) { void pill.offsetWidth; pill.classList.add('bump'); }
      }
      function pillHide() { pill.classList.remove('show', 'bump'); }

      function drawMessage(s, r) {
        var x1 = X(s.from), x2 = X(s.to), y = Y(r), dir = x2 > x1 ? 1 : -1, len = Math.abs(x2 - x1);
        var tone = s.tone || 'neutral';
        var g = svgEl('g', { class: 'tj-g tj-tone-' + tone + (s.return ? ' tj-ret' : '') }, svg);
        var line = svgEl('line', { class: 'tj-arw' + (s.return ? '' : ' draw'), x1: x1, y1: y, x2: x2, y2: y }, g);
        if (!s.return) { line.setAttribute('stroke-dasharray', len); line.setAttribute('stroke-dashoffset', timing(1) > 0 ? len : 0); }
        var hx = x2 - dir * 1, hs = 5;
        svgEl('path', { class: 'tj-head', d: 'M' + hx + ',' + y + ' L' + (hx - dir * hs * 1.6) + ',' + (y - hs) + ' L' + (hx - dir * hs * 1.6) + ',' + (y + hs) + ' Z' }, g);
        var mx = (x1 + x2) / 2;
        if (s.detail) {
          svgEl('text', { class: 'tj-lab strong', x: mx, y: y - 14 }, g).textContent = s.label;
          svgEl('text', { class: 'tj-lab s', x: mx, y: y - 5 }, g).textContent = s.detail;
        } else svgEl('text', { class: 'tj-lab', x: mx, y: y - 6 }, g).textContent = s.label;
        if (s.note) { var nt = svgEl('title', {}, g); nt.textContent = s.note; }
        return function reveal() {
          g.classList.add('on');
          if (!s.return && timing(1) > 0) requestAnimationFrame(function () { requestAnimationFrame(function () { line.setAttribute('stroke-dashoffset', '0'); }); });
          else line.setAttribute('stroke-dashoffset', '0');
        };
      }
      function drawEvent(s, r) {
        var x = X(s.at), y = Y(r), tone = s.tone || 'info';
        var g = svgEl('g', { class: 'tj-g tj-mk tj-tone-' + tone }, svg);
        svgEl('circle', { cx: x, cy: y, r: 10 }, g);
        svgEl('text', { class: 'sym', x: x, y: y + 0.5 }, g).textContent = s.symbol || (tone === 'deny' ? '✗' : tone === 'ok' ? '✓' : '◆');
        var leftSide = col[s.at] === actors.length - 1;          // last lane: label goes left so it stays inside the box
        // If the token pill will rest on this marker, push the label past the pill's half-width so they don't overlap.
        var off = 16 + (s.token && r === lastTokenRow ? s.token.length * 3.2 + 14 : 0);   // only where the pill finally rests
        // Where the pill rests showing the same text as the label (e.g. "200 OK"), the label would only repeat it.
        if (!(r === lastTokenRow && s.token === s.label)) svgEl('text', { class: 'mlab' + (leftSide ? ' left' : ''), x: leftSide ? x - off : x + off, y: y + 3.5 }, g).textContent = s.label;
        if (s.note) { var nt = svgEl('title', {}, g); nt.textContent = s.note; }
        return function reveal() { g.classList.add('on'); };
      }

      var lastTokenRow = -1;
      steps.forEach(function (s, i) { if (s.token) lastTokenRow = i; });
      var reveals = steps.map(function (s, r) { return s.type === 'message' ? drawMessage(s, r) : drawEvent(s, r); });

      function renderFoot() {
        if (!outcome || !outcome.caption) return;
        var ok = outcome.status === 'allow';
        foot.appendChild(el('div', { class: 'tj-cap-line ' + (ok ? 'ok' : 'no') }, [el('span', { class: 'mk', text: ok ? '✓' : '✗' }), el('span', { text: outcome.caption })]));
      }

      // Choreography: for each step reveal it; if it carries a token, the pill shows it moving
      // (message: from -> to) or morphing in place (event). The pill keeps its last position
      // between steps, so a token visibly travels through the whole flow.
      var r = 0;
      function next() {
        if (r >= steps.length) {
          return wait(220, my).then(function () { if (outcome && outcome.status === 'deny' && !steps[steps.length - 1].token) pillHide(); renderFoot(); });
        }
        var s = steps[r], row = r, reveal = reveals[r]; r++;
        if (s.type === 'message') {
          reveal();
          if (s.token) {
            pillTo(X(s.from), Y(row), true); pillShow(s.token, s.tone);
            return wait(160, my).then(function () { pillTo(X(s.to), Y(row)); return wait(560, my); }).then(next);
          }
          return wait(520, my).then(next);
        }
        reveal();
        if (s.token) { pillTo(X(s.at), Y(row), true); pillShow(s.token, s.tone); }
        return wait(s.token ? 460 : 400, my).then(next);
      }
      return wait(120, my).then(next);
    }

    draw();
    return {
      journey: journey,
      setView: setView,
      replay: draw,
      destroy: function () { seq++; clear(container); }
    };
  }

  return { render: render, validate: validate, decodeJwt: decodeJwt, scopesOf: scopesOf, version: '1.0.0' };
});
