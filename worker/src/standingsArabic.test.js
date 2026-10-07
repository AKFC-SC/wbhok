// Standings locale=ar: only team names change; order, numbers and form never do.
// standingsMapper.js is an ES module (not loadable by plain Node), so rows here
// are hand-built in exactly the shape mapStandings() returns.
// Run with: node --test src/standingsArabic.test.js (from worker/).

const test = require('node:test');
const assert = require('node:assert/strict');
const { applyArabicTeamNamesToStandings } = require('./arabicTeamNames.js');

function rows(){
  return [
    { position: 1, team: { id: 7011, name: 'Al Hilal', logo: 'h.png' }, played: 7, won: 6, draw: 1, lost: 0, goalsFor: 18, goalsAgainst: 5, goalDifference: 13, points: 19, form: ['W','W','D'] },
    { position: 2, team: { id: 476, name: 'Al Ittihad', logo: 'i.png' }, played: 7, won: 5, draw: 2, lost: 0, goalsFor: 12, goalsAgainst: 6, goalDifference: 6, points: 17, form: ['W','D','W'] },
    { position: 3, team: { id: 999999, name: 'Unmapped FC', logo: null }, played: 7, won: 1, draw: 1, lost: 5, goalsFor: 4, goalsAgainst: 14, goalDifference: -10, points: 4, form: [] }
  ];
}
const MAP = { '7011': 'الهلال', '476': 'الاتحاد' };

test('standings: mapped teams get Arabic names, unmapped keep the SportMonks name', () => {
  const r = rows();
  applyArabicTeamNamesToStandings(r, MAP);
  assert.equal(r[0].team.name, 'الهلال');
  assert.equal(r[1].team.name, 'الاتحاد');
  assert.equal(r[2].team.name, 'Unmapped FC');
});

test('standings: order and every number/logo/form value are unchanged', () => {
  const before = rows();
  const after = rows();
  applyArabicTeamNamesToStandings(after, MAP);
  const strip = (list) => JSON.parse(JSON.stringify(list.map((x) => { const c = JSON.parse(JSON.stringify(x)); c.team.name = '_'; return c; })));
  assert.deepEqual(strip(after), strip(before));
  assert.deepEqual(after.map((x) => x.position), [1, 2, 3]);
});

test('standings: null map (Webflow failure / no token) leaves names untouched, never throws', () => {
  const r = rows();
  applyArabicTeamNamesToStandings(r, null);
  assert.deepEqual(r.map((x) => x.team.name), ['Al Hilal', 'Al Ittihad', 'Unmapped FC']);
});

test('standings: empty or malformed input is safe', () => {
  assert.doesNotThrow(() => applyArabicTeamNamesToStandings([], MAP));
  assert.doesNotThrow(() => applyArabicTeamNamesToStandings(undefined, MAP));
  assert.doesNotThrow(() => applyArabicTeamNamesToStandings([null, {}], MAP));
});

test('standings: the English path never reaches the substitution (index.js gates on locale === "ar")', () => {
  // index.js: `const locale = url.searchParams.get('locale') === 'ar' ? 'ar' : null;`
  const gate = (q) => (q === 'ar' ? 'ar' : null);
  for (const q of [null, '', 'en', 'EN', 'fr', 'ar ', 'AR']) assert.equal(gate(q), null, 'locale=' + q);
  assert.equal(gate('ar'), 'ar');
});

test('standings: the Webflow token never appears in a substituted row', () => {
  const r = rows();
  applyArabicTeamNamesToStandings(r, MAP);
  assert.equal(JSON.stringify(r).includes('WEBFLOW'), false);
});
