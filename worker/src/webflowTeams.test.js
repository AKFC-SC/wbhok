// Tests for webflowTeams.js — run with: node --test src/webflowTeams.test.js
// (from worker/). No new dependencies: Node's built-in test runner + assert.
//
// index.js itself (ESM, `export default {...}`) is not directly testable by
// plain Node without wrangler's bundler — see the PR/report notes. These
// tests cover the new pure logic this phase actually added: the Webflow team
// lookup, its caching/pagination/fallback behavior, and (in the sibling test
// files) the mapper/previewMapper field additions that feed it.

const test = require('node:test');
const assert = require('node:assert/strict');

// webflowTeams.js keeps isolate-lifetime module state (memoryCache), so each
// test that needs a clean slate re-requires a fresh copy via the cache-clear
// helper below rather than sharing state across tests.
function freshModule(){
  const path = require.resolve('./webflowTeams.js');
  delete require.cache[path];
  return require('./webflowTeams.js');
}

function mockCaches(){
  const store = new Map();
  return {
    default: {
      async match(key){ return store.get(String(key)) || undefined; },
      async put(key, response){ store.set(String(key), response); }
    }
  };
}

test('arabicTeamName: known id returns the Arabic name', () => {
  const { arabicTeamName } = freshModule();
  const map = { '476': 'الاتحاد', '232744': 'الخلود' };
  assert.equal(arabicTeamName(476, map, 'Al Ittihad'), 'الاتحاد');
  assert.equal(arabicTeamName('232744', map, 'Al Kholood'), 'الخلود');
});

test('arabicTeamName: unknown id falls back to the given name, never invents one', () => {
  const { arabicTeamName } = freshModule();
  const map = { '476': 'الاتحاد' };
  assert.equal(arabicTeamName(999999, map, 'Some Team'), 'Some Team');
});

test('arabicTeamName: null map falls back (e.g. lookup never ran or failed)', () => {
  const { arabicTeamName } = freshModule();
  assert.equal(arabicTeamName(476, null, 'Al Ittihad'), 'Al Ittihad');
});

test('arabicTeamName: null/undefined teamId falls back rather than throwing', () => {
  const { arabicTeamName } = freshModule();
  const map = { '476': 'الاتحاد' };
  assert.equal(arabicTeamName(null, map, 'Fallback'), 'Fallback');
  assert.equal(arabicTeamName(undefined, map, 'Fallback'), 'Fallback');
});

test('getTeamArabicNameMap: missing WEBFLOW_API_TOKEN is a safe no-op, never throws', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => { throw new Error('fetch must not be called without a token'); };
  const result = await getTeamArabicNameMap({});
  assert.equal(result.map, null);
  assert.match(result.error, /WEBFLOW_API_TOKEN not configured/);
});

test('getTeamArabicNameMap: builds the map from a single page, skips incomplete records', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  let capturedAuthHeader = null;
  global.fetch = async (url, opts) => {
    capturedAuthHeader = opts.headers.Authorization;
    return {
      ok: true,
      async json(){
        return {
          items: [
            { fieldData: { 'sportsmonks-team-id': '476', name: 'Al Ittihad', 'name-arabic': 'الاتحاد' } },
            { fieldData: { 'sportsmonks-team-id': '232744', name: 'Al Kholood', 'name-arabic': 'الخلود' } },
            // Missing name-arabic — must be skipped, never fabricated.
            { fieldData: { 'sportsmonks-team-id': '148884', name: 'Jeddah', 'name-arabic': null } },
            // Missing sportsmonks-team-id — must be skipped.
            { fieldData: { name: 'No Id Team', 'name-arabic': 'فريق' } }
          ],
          pagination: { limit: 100, offset: 0, total: 4 }
        };
      }
    };
  };

  const result = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token-123' });
  assert.equal(result.error, null);
  assert.deepEqual(result.map, { '476': 'الاتحاد', '232744': 'الخلود' });
  assert.equal(capturedAuthHeader, 'Bearer test-token-123');
});

test('getTeamArabicNameMap: respects pagination across multiple pages', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  const pages = [
    { items: [{ fieldData: { 'sportsmonks-team-id': '1', 'name-arabic': 'أ' } }], pagination: { limit: 1, offset: 0, total: 2 } },
    { items: [{ fieldData: { 'sportsmonks-team-id': '2', 'name-arabic': 'ب' } }], pagination: { limit: 1, offset: 1, total: 2 } }
  ];
  let callCount = 0;
  global.fetch = async () => {
    const page = pages[callCount];
    callCount++;
    return { ok: true, async json(){ return page; } };
  };

  const result = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'tok' });
  assert.deepEqual(result.map, { '1': 'أ', '2': 'ب' });
  assert.equal(callCount, 2, 'expected exactly one fetch per page');
});

test('getTeamArabicNameMap: Webflow API failure degrades to a safe fallback, never throws', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => ({ ok: false, status: 401, async json(){ return {}; } });

  const result = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'bad-token' });
  assert.equal(result.map, null);
  assert.match(result.error, /401/);
});

test('getTeamArabicNameMap: network-level failure (fetch throws) also degrades safely', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => { throw new TypeError('network down'); };

  const result = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'tok' });
  assert.equal(result.map, null);
  assert.match(result.error, /network down/);
});

test('getTeamArabicNameMap: second call within the TTL uses the in-memory cache, does not refetch', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  let fetchCount = 0;
  global.fetch = async () => {
    fetchCount++;
    return {
      ok: true,
      async json(){ return { items: [{ fieldData: { 'sportsmonks-team-id': '476', 'name-arabic': 'الاتحاد' } }], pagination: { limit: 100, offset: 0, total: 1 } }; }
    };
  };

  const env = { WEBFLOW_API_TOKEN: 'tok' };
  const first = await getTeamArabicNameMap(env);
  const second = await getTeamArabicNameMap(env);
  assert.deepEqual(first.map, second.map);
  assert.equal(fetchCount, 1, 'expected only the first call to hit the network');
});

test('getTeamArabicNameMap: no token leakage — the token never appears in the returned result', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => ({
    ok: true,
    async json(){ return { items: [{ fieldData: { 'sportsmonks-team-id': '476', 'name-arabic': 'الاتحاد' } }], pagination: { limit: 100, offset: 0, total: 1 } }; }
  });

  const SECRET = 'super-secret-webflow-token-do-not-leak';
  const result = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: SECRET });
  const serialized = JSON.stringify(result);
  assert.equal(serialized.includes(SECRET), false, 'the Webflow token must never appear in the function result');
});
