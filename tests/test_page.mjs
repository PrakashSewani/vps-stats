#!/usr/bin/env node
//
// Page unit tests — the age maths in web/index.html, with no browser and no dependencies.
//
//   node tests/test_page.mjs        # exit 0 on success, 1 on any failure
//
// The page is one static file with a single inline <script>, so this harness pulls the pure
// functions it wants out of the HTML *by name* and evaluates them in a small sandbox with a
// stubbed clock. Node's own `assert` is the whole toolchain.
//
// Why this file exists. The smoke test's only guard for "the page ages its own numbers" used to
// be `grep -q 'Date.now()'` against the served page, and that check cannot fail: `Date.now()`
// survives both in the degraded no-Date-header path and in the 1 s re-render, so deleting the
// server-clock anchor outright left the check green while the original false-green failure — a
// dead exporter looking brand new on first paint — came straight back. The tests below fail in
// exactly that case.

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = join(HERE, '..', 'web', 'index.html');

const html = readFileSync(PAGE, 'utf8');
const script = /<script>([\s\S]*?)<\/script>/.exec(html);
if (script === null) throw new Error('web/index.html has no inline <script> to test');
const source = script[1];

// A function's source text, braces balanced, so the sandbox runs the page's real code.
function code(name) {
  const start = source.indexOf('function ' + name + '(');
  if (start === -1) throw new Error('web/index.html no longer defines ' + name + '()');
  let depth = 0;
  for (let index = source.indexOf('{', start); index < source.length; index += 1) {
    const character = source[index];
    if (character === '{') depth += 1;
    else if (character === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(name + '() has unbalanced braces in web/index.html');
}

// A constant's value, taken from the page rather than copied here, so the bands under test are
// the bands the page renders with.
function constant(name) {
  const match = new RegExp('const ' + name + ' = ([^;]+);').exec(source);
  if (match === null) throw new Error('web/index.html no longer defines ' + name);
  return match[1];
}

const FUNCTIONS = [
  'finiteNumber',
  'serverTimeSeconds',
  'agedSince',
  'formatNumber',
  'formatInteger',
  'ageMinutes',
  'formatAge',
  'hostAge',
  'hostState'
];
const CONSTANTS = [
  'EM_DASH',
  'VPS_AMBER_AT_SECONDS',
  'VPS_STALE_AT_SECONDS',
  'MAC_AMBER_AT_SECONDS',
  'MAC_STALE_AT_SECONDS'
];

const page = new Function(`
  const NativeDate = globalThis.Date;
  let nowMillis = 0;
  const Date = {now: () => nowMillis, parse: (value) => NativeDate.parse(value)};
  ${CONSTANTS.map((name) => 'const ' + name + ' = ' + constant(name) + ';').join('\n')}
  let ageAnchor = null;
  let latestData = null;
  ${FUNCTIONS.map(code).join('\n')}
  return {
    agedSince,
    ageMinutes,
    formatAge,
    hostAge,
    hostState,
    serverTimeSeconds,
    setNowSeconds(seconds) { nowMillis = seconds * 1000; },
    setAnchor(anchor) { ageAnchor = anchor; }
  };
`)();

const SERVER_EPOCH = 1792165000; // the clock the response Date header reports
const DOCUMENT_EPOCH = SERVER_EPOCH - 370; // a document the exporter stopped refreshing 370 s ago
const SEVEN_HOURS = 7 * 3600;

let failures = 0;
let passes = 0;

function test(name, body) {
  try {
    body();
    passes += 1;
    console.log('ok    ' + name);
  } catch (error) {
    failures += 1;
    console.log('FAIL  ' + name + ' — ' + error.message);
  }
}

test('the response Date header is the anchor source', () => {
  const response = {headers: {get: (name) => (name === 'date' ? 'Fri, 16 Oct 2026 17:13:00 GMT' : null)}};
  assert.equal(page.serverTimeSeconds(response), Date.parse('Fri, 16 Oct 2026 17:13:00 GMT') / 1000);
  assert.equal(page.serverTimeSeconds({headers: {get: () => null}}), null);
});

test('refreshStats anchors to the response, not to the document', () => {
  const refresh = code('refreshStats');
  assert.match(refresh, /serverTimeSeconds\(response\)/, 'the fetch must read the server clock');
  assert.match(refresh, /ageAnchor = /, 'the fetch must capture the age anchor');
});

test('a stalled document reads its true age on first paint', () => {
  page.setNowSeconds(SERVER_EPOCH);
  page.setAnchor({serverEpoch: SERVER_EPOCH, clientEpoch: SERVER_EPOCH});
  assert.equal(Math.round(page.agedSince(DOCUMENT_EPOCH)), 370);
});

test('a browser clock skewed +7 h cannot hide a stalled document', () => {
  // The first term is the data's age on the server's clock; the second is a duration measured
  // from the same skewed clock twice, so the skew cancels. Anchoring on the document's own
  // generated_at instead would cancel its age out and report 0 — the false-green failure.
  const skewed = SERVER_EPOCH + SEVEN_HOURS;
  page.setNowSeconds(skewed);
  page.setAnchor({serverEpoch: SERVER_EPOCH, clientEpoch: skewed});
  assert.equal(Math.round(page.agedSince(DOCUMENT_EPOCH)), 370);
});

test('without the anchor a skewed clock reports hours, which is why the anchor is load-bearing', () => {
  const skewed = SERVER_EPOCH + SEVEN_HOURS;
  page.setNowSeconds(skewed);
  page.setAnchor(null);
  assert.ok(
    page.agedSince(DOCUMENT_EPOCH) > 3600,
    'the degraded path is only reached when the Date header is unusable'
  );
});

test('age never reads negative and handles a missing timestamp', () => {
  page.setNowSeconds(SERVER_EPOCH);
  page.setAnchor({serverEpoch: SERVER_EPOCH, clientEpoch: SERVER_EPOCH});
  assert.equal(page.agedSince(SERVER_EPOCH + 60), 0);
  assert.equal(page.agedSince(null), null);
});

test('the banner and the card share one minute convention', () => {
  // The bug this pins: the banner rounded (`Math.round(age / 60)`) while the card floored, so
  // one document showed "7 min old" in the banner and "6 minutes ago" on the card.
  assert.equal(page.ageMinutes(0), 0);
  assert.equal(page.ageMinutes(59.9), 0);
  assert.equal(page.ageMinutes(90), 1);
  assert.equal(page.ageMinutes(389), 6);
  assert.equal(page.ageMinutes(390), 6, 'a rounded 6.5 must not become 7');
  assert.equal(page.ageMinutes(419), 6);
  assert.equal(page.ageMinutes(420), 7);
  assert.equal(page.ageMinutes(null), null);
  assert.equal(Math.round(390 / 60), 7, 'the rounding this convention replaced');
});

test('formatAge floors its minutes too, matching ageMinutes', () => {
  assert.equal(page.formatAge(2), 'updated just now');
  assert.equal(page.formatAge(30), 'updated 30 seconds ago');
  assert.equal(page.formatAge(390), 'updated 6 minutes ago');
  assert.equal(page.formatAge(430), 'updated 7 minutes ago');
  assert.equal(page.formatAge(3600), 'updated 1 hour ago');
  assert.equal(page.formatAge(null), 'updated —');
  for (const age of [60, 90, 389, 390, 419, 420, 3599]) {
    assert.ok(
      page.formatAge(age).includes(page.ageMinutes(age) + ' minute'),
      'formatAge(' + age + ') disagrees with ageMinutes'
    );
  }
});

test('the banner does not round where the card floors', () => {
  const banner = code('updateBanner');
  assert.match(banner, /ageMinutes\(/, 'the banner must use the shared minute helper');
  assert.doesNotMatch(banner, /Math\.round\(/, 'the banner must not round age to minutes');
});

test('hostState bands follow the page constants', () => {
  const online = {status: 'online'};
  assert.equal(page.hostState('vps', online, 0), 'live');
  assert.equal(page.hostState('vps', online, 44), 'live');
  assert.equal(page.hostState('vps', online, 45), 'amber');
  assert.equal(page.hostState('vps', online, 90), 'stale');
  assert.equal(page.hostState('mac', online, 89), 'live');
  assert.equal(page.hostState('mac', online, 90), 'amber');
  assert.equal(page.hostState('mac', online, 180), 'stale');
  assert.equal(page.hostState('mac', {status: 'asleep'}, 0), 'asleep');
  assert.equal(page.hostState('mac', {status: 'error'}, 0), 'error');
  assert.equal(page.hostState('vps', {status: 'offline'}, 0), 'stale');
  assert.equal(page.hostState('vps', online, null), 'stale');
  assert.equal(page.hostState('vps', null, 0), 'stale');
});

test('hostAge reads the host timestamp through the same anchor', () => {
  page.setNowSeconds(SERVER_EPOCH);
  page.setAnchor({serverEpoch: SERVER_EPOCH, clientEpoch: SERVER_EPOCH});
  assert.equal(Math.round(page.hostAge({generated_at_epoch: DOCUMENT_EPOCH})), 370);
  assert.equal(page.hostAge({}), null, 'a host with no timestamp has no age, not a bogus zero');
});

console.log(failures === 0 ? `${passes} passed` : `${passes} passed, ${failures} failed`);
if (failures > 0) process.exitCode = 1;
