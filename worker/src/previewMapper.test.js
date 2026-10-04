// Regression test for previewMapper.js's new homeTeamId/awayTeamId (H2H) and
// opponentId (last-5) fields, plus a check that existing fields survive.
// Run with: node --test src/previewMapper.test.js (from worker/).

const test = require('node:test');
const assert = require('node:assert/strict');
const { mapFixtureCore, mapH2H, mapLastFive } = require('./previewMapper.js');

test('mapFixtureCore: home/away already carried id before this phase — still does', () => {
  const fixture = {
    participants: [
      { id: 476, name: 'Al Ittihad', image_path: 'https://cdn/476.png', meta: { location: 'home' } },
      { id: 232744, name: 'Al Kholood', image_path: 'https://cdn/232744.png', meta: { location: 'away' } }
    ],
    league: { name: 'Pro League' },
    venue: { name: 'Alinma Stadium' },
    starting_at: '2026-08-15T18:00:00.000000Z',
    state: { name: 'Not Started' }
  };
  const core = mapFixtureCore(fixture);
  assert.equal(core.home.id, 476);
  assert.equal(core.away.id, 232744);
  assert.equal(core.home.name, 'Al Ittihad');
  assert.equal(core.away.name, 'Al Kholood');
});

function h2hFixture(homeId, homeName, awayId, awayName, homeGoals, awayGoals, startingAt){
  return {
    participants: [
      { id: homeId, name: homeName, image_path: 'https://cdn/home.png', meta: { location: 'home' } },
      { id: awayId, name: awayName, image_path: 'https://cdn/away.png', meta: { location: 'away' } }
    ],
    scores: [
      { participant_id: homeId, description: 'CURRENT', score: { goals: homeGoals } },
      { participant_id: awayId, description: 'CURRENT', score: { goals: awayGoals } }
    ],
    league: { name: 'Pro League' },
    starting_at: startingAt
  };
}

test('mapH2H: each meeting now carries homeTeamId/awayTeamId', () => {
  const fixtures = [h2hFixture(476, 'Al Ittihad', 232744, 'Al Kholood', 1, 1, '2026-08-15T18:00:00.000000Z')];
  const h2h = mapH2H(fixtures, 476, 232744);
  assert.equal(h2h.meetings.length, 1);
  assert.equal(h2h.meetings[0].homeTeamId, 476);
  assert.equal(h2h.meetings[0].awayTeamId, 232744);
});

test('mapH2H: pre-existing meeting fields are unchanged', () => {
  const fixtures = [h2hFixture(476, 'Al Ittihad', 232744, 'Al Kholood', 2, 1, '2026-08-15T18:00:00.000000Z')];
  const h2h = mapH2H(fixtures, 476, 232744);
  const m = h2h.meetings[0];
  assert.equal(m.homeTeam, 'Al Ittihad');
  assert.equal(m.awayTeam, 'Al Kholood');
  assert.equal(m.homeScore, 2);
  assert.equal(m.awayScore, 1);
  assert.equal(m.competition, 'Pro League');
  assert.equal(h2h.summary.homeWins, 1);
});

test('mapLastFive: each entry now carries opponentId, existing fields unchanged', () => {
  const fixturesInWindow = [
    {
      id: 999,
      state: { name: 'Full Time' },
      league: { name: 'Pro League' },
      starting_at: '2026-08-01T18:00:00.000000Z',
      participants: [
        { id: 232744, name: 'Al Kholood', meta: { location: 'home' } },
        { id: 476, name: 'Al Ittihad', image_path: 'https://cdn/476.png', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: 232744, description: 'CURRENT', score: { goals: 2 } },
        { participant_id: 476, description: 'CURRENT', score: { goals: 1 } }
      ]
    }
  ];
  const last5 = mapLastFive(fixturesInWindow, 232744, 'not-this-fixture-id');
  assert.equal(last5.length, 1);
  assert.equal(last5[0].opponentId, 476);
  assert.equal(last5[0].opponent, 'Al Ittihad');
  assert.equal(last5[0].result, 'W');
  assert.equal(last5[0].selfScore, 2);
  assert.equal(last5[0].opponentScore, 1);
});

test('mapLastFive: excludes the current pre-match fixture by id', () => {
  const fixturesInWindow = [
    {
      id: 19777719,
      state: { name: 'Full Time' },
      league: { name: 'Pro League' },
      starting_at: '2026-08-15T18:00:00.000000Z',
      participants: [
        { id: 232744, name: 'Al Kholood', meta: { location: 'home' } },
        { id: 476, name: 'Al Ittihad', meta: { location: 'away' } }
      ],
      scores: [
        { participant_id: 232744, description: 'CURRENT', score: { goals: 1 } },
        { participant_id: 476, description: 'CURRENT', score: { goals: 1 } }
      ]
    }
  ];
  const last5 = mapLastFive(fixturesInWindow, 232744, '19777719');
  assert.equal(last5.length, 0);
});
