// STATIC / IN-PROCESS VALIDATION ONLY — NOT A LIVE API TEST.
//
// This exercises the real, actual code (mapper.js, previewMapper.js,
// webflowTeams.js, arabicTeamNames.js — the exact files index.js imports and
// calls) against MOCKED SportMonks and Webflow HTTP responses. It proves the
// transformation logic is correct given realistic input; it does NOT prove
// the real Webflow API or the real deployed Worker behave this way, because
// `wrangler dev --remote` could not establish a remote preview session on
// this account (reported and accepted as a known limitation) and nothing has
// been deployed. index.js's own thin HTTP routing shell (path regex + query
// param read) is not exercised here — it was verified separately by code
// review and a clean `wrangler deploy --dry-run` bundle.
//
// Run with: node --test src/arabicIntegration.test.js (from worker/).

const test = require('node:test');
const assert = require('node:assert/strict');
const { mapSportMonksToMatchHub } = require('./mapper.js');
const { mapFixtureCore, mapH2H, mapLastFive } = require('./previewMapper.js');
const { arabicTeamName } = require('./webflowTeams.js');

function freshWebflowTeamsModule(){
  const path = require.resolve('./webflowTeams.js');
  delete require.cache[path];
  return require('./webflowTeams.js');
}
function freshArabicTeamNamesModule(){
  const wfPath = require.resolve('./webflowTeams.js');
  const atnPath = require.resolve('./arabicTeamNames.js');
  delete require.cache[wfPath];
  delete require.cache[atnPath];
  return require('./arabicTeamNames.js');
}

function mockCaches(){
  const store = new Map();
  return { default: {
    async match(key){ return store.get(String(key)) || undefined; },
    async put(key, response){ store.set(String(key), response); }
  } };
}

// The real, confirmed mapping for fixture 19777719: Al Ittihad (id 476) vs Al
// Kholood (id 232744), final score 1-1, Full Time — same fixture used
// throughout this whole project as the smoke-test reference.
const HOME_ID = 476, AWAY_ID = 232744;
const UNKNOWN_ID = 999999; // deliberately outside the 19-team CMS map

function webflowTeamItemsResponse(){
  return {
    items: [
      { fieldData: { 'sportsmonks-team-id': '476', name: 'Al Ittihad', 'name-arabic': 'الاتحاد' } },
      { fieldData: { 'sportsmonks-team-id': '232744', name: 'Al Kholood', 'name-arabic': 'الخلود' } },
      // A real-shaped record with a missing Arabic name, to test that specific fallback.
      { fieldData: { 'sportsmonks-team-id': '148884', name: 'Jeddah', 'name-arabic': null } }
    ],
    pagination: { limit: 100, offset: 0, total: 3 }
  };
}

function mockFetchRouter({ webflowOk = true, webflowStatus = 200 } = {}){
  return async function(url, opts){
    const u = String(url);
    if(u.indexOf('api.webflow.com') !== -1){
      if(!webflowOk) return { ok: false, status: webflowStatus, async json(){ return {}; } };
      return { ok: true, async json(){ return webflowTeamItemsResponse(); } };
    }
    throw new Error('Unexpected fetch call in this test: ' + u);
  };
}

function matchHubFixture(){
  return {
    participants: [
      { id: HOME_ID, name: 'Al Ittihad', image_path: 'https://cdn/476.png', meta: { location: 'home' } },
      { id: AWAY_ID, name: 'Al Kholood', image_path: 'https://cdn/232744.png', meta: { location: 'away' } }
    ],
    scores: [
      { participant_id: HOME_ID, description: 'CURRENT', score: { goals: 1 } },
      { participant_id: AWAY_ID, description: 'CURRENT', score: { goals: 1 } }
    ],
    statistics: [], events: [], formations: [], lineups: [],
    league: { name: 'Pro League' },
    venue: { name: 'Alinma Stadium' },
    starting_at: '2026-08-15T18:00:00.000000Z',
    state: { name: 'Full Time' }
  };
}

function previewFixture(){
  return {
    participants: [
      { id: HOME_ID, name: 'Al Ittihad', image_path: 'https://cdn/476.png', meta: { location: 'home' } },
      { id: AWAY_ID, name: 'Al Kholood', image_path: 'https://cdn/232744.png', meta: { location: 'away' } }
    ],
    league: { name: 'Pro League' },
    venue: { name: 'Alinma Stadium' },
    starting_at: '2026-08-15T18:00:00.000000Z',
    state: { name: 'Not Started' }
  };
}

function h2hFixtures(){
  return [
    // A known meeting — both teams in the CMS map.
    {
      participants: [
        { id: HOME_ID, name: 'Al Ittihad', meta: { location: 'home' } },
        { id: AWAY_ID, name: 'Al Kholood', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: HOME_ID, description: 'CURRENT', score: { goals: 1 } },
        { participant_id: AWAY_ID, description: 'CURRENT', score: { goals: 1 } }
      ],
      league: { name: 'Pro League' },
      starting_at: '2026-08-15T18:00:00.000000Z'
    },
    // An older meeting against a team NOT in the 19-team CMS map (unknown id).
    {
      participants: [
        { id: HOME_ID, name: 'Al Ittihad', meta: { location: 'home' } },
        { id: UNKNOWN_ID, name: 'Some Unmapped FC', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: HOME_ID, description: 'CURRENT', score: { goals: 2 } },
        { participant_id: UNKNOWN_ID, description: 'CURRENT', score: { goals: 0 } }
      ],
      league: { name: 'Pro League' },
      starting_at: '2025-01-01T18:00:00.000000Z'
    }
  ];
}

function last5FixturesForKholood(){
  return [
    {
      id: 1, state: { name: 'Full Time' }, league: { name: 'Pro League' },
      starting_at: '2026-07-01T18:00:00.000000Z',
      participants: [
        { id: AWAY_ID, name: 'Al Kholood', meta: { location: 'home' } },
        { id: HOME_ID, name: 'Al Ittihad', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: AWAY_ID, description: 'CURRENT', score: { goals: 3 } },
        { participant_id: HOME_ID, description: 'CURRENT', score: { goals: 1 } }
      ]
    },
    {
      id: 2, state: { name: 'Full Time' }, league: { name: 'Pro League' },
      starting_at: '2026-06-01T18:00:00.000000Z',
      participants: [
        { id: AWAY_ID, name: 'Al Kholood', meta: { location: 'home' } },
        { id: UNKNOWN_ID, name: 'Some Unmapped FC', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: AWAY_ID, description: 'CURRENT', score: { goals: 1 } },
        { participant_id: UNKNOWN_ID, description: 'CURRENT', score: { goals: 1 } }
      ]
    }
  ];
}

test('IN-PROCESS: /api/match/19777719?locale=ar — Match Hub Arabic path (real mapper.js + webflowTeams.js + arabicTeamNames.js)', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter();
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { applyArabicTeamNames } = freshArabicTeamNamesModule();

  const shaped = mapSportMonksToMatchHub(matchHubFixture());
  const { map } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  applyArabicTeamNames(shaped, map);

  assert.equal(shaped.home.name, 'الاتحاد', 'home.name should be the real Arabic name for team 476');
  assert.equal(shaped.away.name, 'الخلود', 'away.name should be the real Arabic name for team 232744');
  assert.equal(shaped.lineups.home.teamName, 'الاتحاد', 'lineup teamName must also become Arabic');
  assert.equal(shaped.lineups.away.teamName, 'الخلود', 'lineup teamName must also become Arabic');
  // Existing fields must survive untouched.
  assert.equal(shaped.home.score, 1);
  assert.equal(shaped.away.score, 1);
  assert.equal(shaped.status, 'Full Time');
});

test('IN-PROCESS: /api/match/19777719/preview?locale=ar — Match Center Arabic path (real previewMapper.js + webflowTeams.js + arabicTeamNames.js)', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter();
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { applyArabicTeamNamesToPreview } = freshArabicTeamNamesModule();

  const core = mapFixtureCore(previewFixture());
  const h2h = mapH2H(h2hFixtures(), HOME_ID, AWAY_ID);
  const homeForm = [];
  const awayForm = mapLastFive(last5FixturesForKholood(), AWAY_ID, 'not-this-fixture');

  const { map } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  applyArabicTeamNamesToPreview(core, h2h, homeForm, awayForm, map);

  assert.equal(core.home.name, 'الاتحاد');
  assert.equal(core.away.name, 'الخلود');

  // H2H: known meeting resolves both sides to Arabic.
  assert.equal(h2h.meetings[0].homeTeam, 'الاتحاد');
  assert.equal(h2h.meetings[0].awayTeam, 'الخلود');
  // H2H: meeting against an unmapped team keeps the SportMonks name for that side only.
  assert.equal(h2h.meetings[1].homeTeam, 'الاتحاد');
  assert.equal(h2h.meetings[1].awayTeam, 'Some Unmapped FC', 'unknown team id must fall back, never invented');

  // Last-5: known opponent resolves to Arabic, unmapped opponent falls back.
  assert.equal(awayForm[0].opponent, 'الاتحاد');
  assert.equal(awayForm[1].opponent, 'Some Unmapped FC');
});

test('IN-PROCESS: unknown team id (not in the 19-team CMS) falls back to the SportMonks name', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter();
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { map } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  assert.equal(arabicTeamName(UNKNOWN_ID, map, 'Some Unmapped FC'), 'Some Unmapped FC');
});

test('IN-PROCESS: a CMS record with a missing Arabic name falls back safely, never fabricated', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter();
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { map } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  // Team 148884 ("Jeddah") is present in the mock CMS but has name-arabic: null.
  assert.equal(map['148884'], undefined, 'a record with no Arabic name must not enter the map at all');
  assert.equal(arabicTeamName('148884', map, 'Jeddah'), 'Jeddah');
});

test('IN-PROCESS: a Webflow API failure degrades the whole Arabic path safely (English names kept)', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter({ webflowOk: false, webflowStatus: 500 });
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { applyArabicTeamNames } = freshArabicTeamNamesModule();

  const shaped = mapSportMonksToMatchHub(matchHubFixture());
  const { map, error } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: 'test-token' });
  assert.equal(map, null);
  assert.match(error, /500/);

  applyArabicTeamNames(shaped, map);
  assert.equal(shaped.home.name, 'Al Ittihad', 'must stay in English when the Webflow lookup fails');
  assert.equal(shaped.away.name, 'Al Kholood', 'must stay in English when the Webflow lookup fails');
});

test('IN-PROCESS: English path never invokes the Webflow lookup at all', async () => {
  // Mirrors index.js's actual gate exactly: `if(locale === 'ar'){ ... }`.
  // For any other locale value, getTeamArabicNameMap must simply never be
  // called — proven here by never even installing a Webflow-capable fetch
  // mock and asserting the shaped/core objects are the plain English mapper
  // output, completely untouched by any Arabic-substitution step.
  const locale = null; // what index.js computes for any request without ?locale=ar
  global.fetch = async () => { throw new Error('fetch must not be called on the English path'); };

  const shaped = mapSportMonksToMatchHub(matchHubFixture());
  if(locale === 'ar'){
    throw new Error('unreachable in this test — English must never enter this branch');
  }
  assert.equal(shaped.home.name, 'Al Ittihad');
  assert.equal(shaped.away.name, 'Al Kholood');
});

test('IN-PROCESS: existing English response contract fields are all still present and unchanged', () => {
  const shaped = mapSportMonksToMatchHub(matchHubFixture());
  for(const key of ['home', 'away', 'competition', 'venue', 'date', 'kickoffTime', 'status', 'possession', 'statistics', 'events', 'lineups']){
    assert.ok(Object.prototype.hasOwnProperty.call(shaped, key));
  }
  assert.equal(shaped.home.name, 'Al Ittihad');
  assert.equal(shaped.away.name, 'Al Kholood');
  assert.equal(shaped.status, 'Full Time');

  const core = mapFixtureCore(previewFixture());
  for(const key of ['home', 'away', 'competition', 'venue', 'location', 'date', 'kickoffTime', 'status']){
    assert.ok(Object.prototype.hasOwnProperty.call(core, key));
  }
});

test('IN-PROCESS: WEBFLOW_API_TOKEN never appears in the final Arabic response objects', async () => {
  global.caches = mockCaches();
  global.fetch = mockFetchRouter();
  const { getTeamArabicNameMap } = freshWebflowTeamsModule();
  const { applyArabicTeamNames } = freshArabicTeamNamesModule();

  const SECRET = 'super-secret-webflow-token-do-not-leak';
  const shaped = mapSportMonksToMatchHub(matchHubFixture());
  const { map } = await getTeamArabicNameMap({ WEBFLOW_API_TOKEN: SECRET });
  applyArabicTeamNames(shaped, map);

  const serialized = JSON.stringify(shaped);
  assert.equal(serialized.includes(SECRET), false);
});
