// Tests for the U21 Arabic team-name mechanism — run: node --test src/u21Arabic.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const AR = '6a671465e31c8cf8983d3d0d';
const EN = '6a671465e31c8cf8983d3d0c';

function freshModule(){
  const path = require.resolve('./webflowTeams.js');
  delete require.cache[path];
  return require('./webflowTeams.js');
}
function mockCaches(){
  const store = new Map();
  return { default: {
    async match(k){ return store.get(String(k)) || undefined; },
    async put(k, r){ store.set(String(k), r); }
  } };
}
const row = (id, name, loc = AR, extra = {}) => ({ id: 'i' + id, cmsLocaleId: loc, isArchived: false, fieldData: { 'sportsmonks-team-id': String(id), name }, ...extra });

// The 24 club-supplied mappings (SportMonks U21 team id -> exact Arabic name).
const OFFICIAL = {
  280638: 'الاتحاد', 280640: 'الفتح', 280647: 'الأهلي', 280636: 'القادسية', 280642: 'الهلال', 280648: 'الرياض',
  280646: 'الخلود', 280645: 'الاتفاق', 280637: 'الفيحاء', 280643: 'التعاون', 281608: 'الفيصلي', 280654: 'الخليج',
  280639: 'نيوم', 280644: 'النصر', 280656: 'الجبلين', 280641: 'الوحدة', 280635: 'الحزم', 280651: 'ضمك',
  281610: 'الوطن', 280652: 'النجمة', 281609: 'الأنصار', 280634: 'الأخدود', 280653: 'العروبة', 281607: 'التضامن'
};

test('buildU21TeamMap: only Arabic-locale rows with an Arabic-script name are used', () => {
  const { buildU21TeamMap } = freshModule();
  const map = buildU21TeamMap([
    row(1, 'الهلال'),                       // ok
    row(2, 'Al Ittihad U21'),               // English name in the Arabic row -> never used
    row(3, 'الاتحاد', EN),                  // Primary-locale row -> never used
    { ...row(4, 'النصر'), isArchived: true }, // archived -> skipped
    row(5, ''),                             // empty -> skipped
    { id: 'x', cmsLocaleId: AR, fieldData: { name: 'الخلود' } } // no team id -> skipped
  ]);
  assert.deepEqual(map, { 1: 'الهلال' });
});

test('getU21TeamArabicNameMap: requests the U21 collection in the Arabic locale, builds all 24', async () => {
  const { getU21TeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  const urls = [];
  global.fetch = async (url, opts) => {
    urls.push({ url, auth: opts.headers.Authorization });
    const items = Object.entries(OFFICIAL).map(([id, n]) => row(id, n));
    return { ok: true, status: 200, json: async () => ({ items, pagination: { total: items.length } }) };
  };
  const r = await getU21TeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  assert.equal(r.error, null);
  assert.equal(Object.keys(r.map).length, 24);
  for(const [id, name] of Object.entries(OFFICIAL)) assert.equal(r.map[id], name, 'team ' + id);
  assert.match(urls[0].url, /collections\/6a9c273b2ce0ff1e94791189\/items/);
  assert.match(urls[0].url, /cmsLocaleId=6a671465e31c8cf8983d3d0d/);
  assert.equal(JSON.stringify(r).includes('test-token'), false);
});

test('getU21TeamArabicNameMap: no token / API failure degrade safely and never throw', async () => {
  let m = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => { throw new Error('must not be called'); };
  let r = await m.getU21TeamArabicNameMap({});
  assert.equal(r.map, null); assert.match(r.error, /not configured/);
  m = freshModule();
  global.caches = mockCaches();
  global.fetch = async () => ({ ok: false, status: 500, json: async () => ({}) });
  r = await m.getU21TeamArabicNameMap({ WEBFLOW_API_TOKEN: 't' });
  assert.equal(r.map, null); assert.match(r.error, /500/);
});

test('getTeamArabicNameMap (First Team) request is unchanged: no cmsLocaleId param', async () => {
  const { getTeamArabicNameMap } = freshModule();
  global.caches = mockCaches();
  let url;
  global.fetch = async (u) => { url = u; return { ok: true, status: 200, json: async () => ({ items: [], pagination: { total: 0 } }) }; };
  await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 't' });
  assert.match(url, /collections\/6a9c2ff98dd513bfc472db69\/items\?limit=100&offset=0$/);
});

test('standings: U21 + First Team maps merge; order/numbers untouched; unmapped keep their name', () => {
  const { applyArabicTeamNamesToStandings } = require('./arabicTeamNames.js');
  const merged = Object.assign({}, { 476: 'الاتحاد' }, { 280638: 'الاتحاد', 280646: 'الخلود' });
  const rows = [
    { position: 1, points: 9, team: { id: 280638, name: 'Al Ittihad U21' } },
    { position: 2, points: 7, team: { id: 280646, name: 'Al Kholood U21' } },
    { position: 3, points: 1, team: { id: 999, name: 'Unknown U21' } }
  ];
  const before = JSON.parse(JSON.stringify(rows));
  applyArabicTeamNamesToStandings(rows, merged);
  assert.deepEqual(rows.map(r => r.team.name), ['الاتحاد', 'الخلود', 'Unknown U21']);
  assert.deepEqual(rows.map(r => [r.position, r.points]), before.map(r => [r.position, r.points]));
});
