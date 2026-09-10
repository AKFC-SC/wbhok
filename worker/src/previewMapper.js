// Pure mapper: raw SportMonks v3 responses -> Match Center (pre-match) contract.
// No framework dependency, no network calls, no secrets. Mirrors mapper.js's style
// and discipline: every field either comes straight off a confirmed SportMonks
// response shape, or is left null with a comment explaining why it isn't guessed.
//
// Base fixture fields (participants, starting_at, venue.name, league.name,
// state.name) are CONFIRMED — mapper.js and sync.py already read these exact
// keys off real fixture responses (19777719 completed, 19779165 upcoming).
//
// The head-to-head and fixtures/between endpoints below follow SportMonks' v3
// documented shapes. fixtures/between/{start}/{end}/{teamId} is already used
// (confirmed working) in sync.py for a different purpose (syncing upcoming
// fixtures) — reused here unchanged, just for a past date range instead of a
// future one. The head-to-head endpoint (fixtures/head-to-head/{id1}/{id2}) is
// NOT previously used anywhere in this codebase, so unlike everything else here
// it has not been empirically confirmed against a real Al Kholood opponent pair.
// It is implemented defensively (try/catch, null-safe field access) so a wrong
// assumption fails closed to an empty h2h object rather than throwing or
// fabricating data — confirm it against a real response before fully trusting it.

var RIYADH_OFFSET_HOURS = 3;
var COMPLETED_STATE = 'Full Time'; // confirmed sentinel, same one mapper.js documents and the Home page JS already checks against

function findParticipant(participants, location){
  return (participants || []).find(function(p){
    return (p.meta || {}).location === location; // 'home' | 'away'
  }) || null;
}

function scoreFor(scores, participantId){
  var entry = (scores || []).find(function(s){
    return s.participant_id === participantId && s.description === 'CURRENT';
  });
  return entry && entry.score ? entry.score.goals : null;
}

// Formats like sync.py's fixture_date()/fixture_time(): starting_at is UTC ISO,
// converted to Riyadh local time using the same fixed +3h offset already used by
// the site's own countdown script (RIYADH_OFFSET_HOURS) rather than a timezone
// library the Worker doesn't have.
function formatDate(startingAt){
  if(!startingAt) return null;
  var d = new Date(startingAt);
  if(isNaN(d.getTime())) return null;
  var riyadh = new Date(d.getTime() + RIYADH_OFFSET_HOURS * 3600 * 1000);
  var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  return months[riyadh.getUTCMonth()] + ' ' + riyadh.getUTCDate() + ', ' + riyadh.getUTCFullYear();
}

function formatTime(startingAt){
  if(!startingAt) return null;
  var d = new Date(startingAt);
  if(isNaN(d.getTime())) return null;
  var riyadh = new Date(d.getTime() + RIYADH_OFFSET_HOURS * 3600 * 1000);
  var hours = riyadh.getUTCHours();
  var minutes = riyadh.getUTCMinutes();
  var ampm = hours >= 12 ? 'PM' : 'AM';
  var h12 = hours % 12;
  if(h12 === 0) h12 = 12;
  return h12 + ':' + (minutes < 10 ? '0' : '') + minutes + ' ' + ampm;
}

// Base fixture -> hero + match-information fields. Same participants/venue/league/
// state keys mapper.js and sync.py already confirmed; starting_at is a base
// SportMonks fixture field (no extra include needed), confirmed via sync.py's
// fixture_date()/fixture_time(). "location" (a city distinct from the venue name)
// is NOT confirmed anywhere in this codebase — left null rather than guessed.
function mapFixtureCore(fixture){
  var participants = fixture.participants || [];
  var home = findParticipant(participants, 'home');
  var away = findParticipant(participants, 'away');

  return {
    home: { id: home ? home.id : null, name: home ? home.name : '', logo: home ? home.image_path : '' },
    away: { id: away ? away.id : null, name: away ? away.name : '', logo: away ? away.image_path : '' },
    competition: fixture.league ? fixture.league.name : '',
    venue: fixture.venue ? fixture.venue.name : '',
    location: null, // not confirmed on this plan — see header comment, never fabricated
    date: formatDate(fixture.starting_at),
    kickoffTime: formatTime(fixture.starting_at),
    status: fixture.state ? fixture.state.name : null
  };
}

// SportMonks head-to-head fixtures come back oldest/newest order unconfirmed;
// sorted explicitly by starting_at desc here so "most recent first" doesn't
// depend on an assumption about API ordering.
function mapH2H(h2hFixtures, homeId, awayId){
  var meetings = (h2hFixtures || []).map(function(fx){
    var participants = fx.participants || [];
    var fxHome = findParticipant(participants, 'home');
    var fxAway = findParticipant(participants, 'away');
    var scores = fx.scores || [];
    return {
      date: formatDate(fx.starting_at),
      competition: fx.league ? fx.league.name : '',
      homeTeam: fxHome ? fxHome.name : '',
      homeLogo: fxHome ? (fxHome.image_path || null) : null,
      awayTeam: fxAway ? fxAway.name : '',
      awayLogo: fxAway ? (fxAway.image_path || null) : null,
      homeScore: fxHome ? scoreFor(scores, fxHome.id) : null,
      awayScore: fxAway ? scoreFor(scores, fxAway.id) : null,
      _startingAt: fx.starting_at,
      _homeParticipantId: fxHome ? fxHome.id : null
    };
  }).filter(function(m){ return m.homeScore != null && m.awayScore != null; }) // only decided meetings count toward the record
    .sort(function(a, b){ return new Date(b._startingAt) - new Date(a._startingAt); });

  var homeWins = 0, draws = 0, awayWins = 0;
  meetings.forEach(function(m){
    // homeWins/awayWins are relative to the CURRENT fixture's home/away teams,
    // not to whichever side happened to be "home" in that historical meeting.
    var currentHomeScore = (m._homeParticipantId === homeId) ? m.homeScore : m.awayScore;
    var currentAwayScore = (m._homeParticipantId === homeId) ? m.awayScore : m.homeScore;
    if(currentHomeScore > currentAwayScore) homeWins++;
    else if(currentHomeScore < currentAwayScore) awayWins++;
    else draws++;
  });

  return {
    summary: { homeWins: homeWins, draws: draws, awayWins: awayWins },
    meetings: meetings.map(function(m){
      return { date: m.date, competition: m.competition, homeTeam: m.homeTeam, homeLogo: m.homeLogo, homeScore: m.homeScore, awayTeam: m.awayTeam, awayLogo: m.awayLogo, awayScore: m.awayScore };
    })
  };
}

// One team's last 5 *completed* fixtures from a fixtures/between window, most
// recent first, with the current (pre-match) fixture explicitly excluded.
function mapLastFive(fixturesInWindow, teamId, excludeFixtureId){
  var completed = (fixturesInWindow || [])
    .filter(function(fx){ return String(fx.id) !== String(excludeFixtureId); })
    .filter(function(fx){ return fx.state && fx.state.name === COMPLETED_STATE; })
    .map(function(fx){
      var participants = fx.participants || [];
      var self = participants.find(function(p){ return p.id === teamId; });
      var opponent = participants.find(function(p){ return p.id !== teamId; });
      if(!self || !opponent) return null;
      var isHome = (self.meta || {}).location === 'home';
      var scores = fx.scores || [];
      var selfScore = scoreFor(scores, self.id);
      var oppScore = scoreFor(scores, opponent.id);
      if(selfScore == null || oppScore == null) return null;
      var result = selfScore > oppScore ? 'W' : (selfScore < oppScore ? 'L' : 'D');
      return {
        opponent: opponent.name,
        opponentLogo: opponent.image_path || null,
        isHome: isHome,
        result: result,
        selfScore: selfScore,
        opponentScore: oppScore,
        competition: fx.league ? fx.league.name : '',
        date: formatDate(fx.starting_at),
        _startingAt: fx.starting_at
      };
    })
    .filter(Boolean)
    .sort(function(a, b){ return new Date(b._startingAt) - new Date(a._startingAt); })
    .slice(0, 5);

  return completed.map(function(m){
    return { opponent: m.opponent, opponentLogo: m.opponentLogo, isHome: m.isHome, result: m.result, selfScore: m.selfScore, opponentScore: m.opponentScore, competition: m.competition, date: m.date };
  });
}

module.exports = {
  mapFixtureCore: mapFixtureCore,
  mapH2H: mapH2H,
  mapLastFive: mapLastFive,
  formatDate: formatDate,
  formatTime: formatTime
};
