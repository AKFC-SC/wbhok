// Regression test for mapper.js's new `id` field on home/away, plus a check
// that every pre-existing top-level field this phase did NOT intend to touch
// is still present. Run with: node --test src/mapper.test.js (from worker/).
//
// Uses a synthetic fixture shaped like the confirmed real SportMonks response
// (same field names the file's own header comments document against fixture
// 19777719) rather than a live network call — this is a unit test of the
// pure mapping function, not an integration test against SportMonks.

const test = require('node:test');
const assert = require('node:assert/strict');
const { mapSportMonksToMatchHub } = require('./mapper.js');

function syntheticFixture(){
  return {
    participants: [
      { id: 476, name: 'Al Ittihad', image_path: 'https://cdn/476.png', meta: { location: 'home' } },
      { id: 232744, name: 'Al Kholood', image_path: 'https://cdn/232744.png', meta: { location: 'away' } }
    ],
    scores: [
      { participant_id: 476, description: 'CURRENT', score: { goals: 1 } },
      { participant_id: 232744, description: 'CURRENT', score: { goals: 1 } }
    ],
    statistics: [],
    events: [],
    formations: [],
    lineups: [],
    league: { name: 'Pro League' },
    venue: { name: 'Alinma Stadium' },
    starting_at: '2026-08-15T18:00:00.000000Z',
    state: { name: 'Full Time' }
  };
}

test('mapSportMonksToMatchHub: home/away now carry the SportMonks team id', () => {
  const shaped = mapSportMonksToMatchHub(syntheticFixture());
  assert.equal(shaped.home.id, 476);
  assert.equal(shaped.away.id, 232744);
});

test('mapSportMonksToMatchHub: pre-existing home/away fields are unchanged', () => {
  const shaped = mapSportMonksToMatchHub(syntheticFixture());
  assert.equal(shaped.home.name, 'Al Ittihad');
  assert.equal(shaped.home.logo, 'https://cdn/476.png');
  assert.equal(shaped.home.score, 1);
  assert.equal(shaped.away.name, 'Al Kholood');
  assert.equal(shaped.away.logo, 'https://cdn/232744.png');
  assert.equal(shaped.away.score, 1);
});

test('mapSportMonksToMatchHub: every other top-level contract field is still present', () => {
  const shaped = mapSportMonksToMatchHub(syntheticFixture());
  for(const key of ['competition', 'venue', 'date', 'kickoffTime', 'status', 'possession', 'statistics', 'events', 'lineups']){
    assert.ok(Object.prototype.hasOwnProperty.call(shaped, key), `expected "${key}" to still be present`);
  }
  assert.equal(shaped.competition, 'Pro League');
  assert.equal(shaped.venue, 'Alinma Stadium');
  assert.equal(shaped.status, 'Full Time');
});

test('mapSportMonksToMatchHub: missing participant yields id: null, not a throw', () => {
  const fixture = syntheticFixture();
  fixture.participants = [fixture.participants[0]]; // drop away
  const shaped = mapSportMonksToMatchHub(fixture);
  assert.equal(shaped.home.id, 476);
  assert.equal(shaped.away.id, null);
  assert.equal(shaped.away.name, '');
});
