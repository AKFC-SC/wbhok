// Pure mapper: raw SportMonks v3 fixture response -> Match Hub contract (see ../../contract.md).
// No framework dependency, no network calls, no secrets. Safe to unit test on its own.
//
// CONFIRMED against a real API response (fixture 19777719, Al Ittihad vs Al Kholood,
// completed match) and a real upcoming fixture (19779165, state NS) on 2026-08-26,
// on a SportMonks "Starter / Advanced" Football plan. Every type_id below was read
// directly off that response — nothing here is guessed or assumed.
//
// Required request:
//   GET https://api.sportmonks.com/v3/football/fixtures/{id}
//     ?api_token=...
//     &include=participants;venue;league;state;scores;formations;events.type;
//               lineups.player;lineups.position;lineups.details.type;statistics.type
//
// Confirmed behavior for an upcoming (not-yet-played) fixture: scores, events,
// lineups, statistics, and formations all come back as empty arrays (not missing
// keys, not errors) — this mapper's defaults already produce a clean all-empty
// contract object in that case, no special-casing needed.

const EVENT_TYPE_IDS = {
  GOAL: 14,             // confirmed: 2 real goal events in test fixture
  SUBSTITUTION: 18,      // confirmed: 8 real substitution events
  YELLOW_CARD: 19,       // confirmed: 2 real yellow-card events
  RED_CARD: 20,          // confirmed: 1 real red-card event
  MISSED_PENALTY: 17,    // confirmed present (1 event), not currently surfaced in the UI contract
  VAR_CARD: 1697         // confirmed present (1 event), not currently surfaced in the UI contract
  // OWN_GOAL, PENALTY_GOAL, YELLOW_RED_CARD did not appear in the test fixture and
  // are intentionally omitted rather than guessed. If one of these occurs in a real
  // fixture and needs handling, confirm its type_id from that fixture's response
  // before adding it here.
};

const LINEUP_TYPE_IDS = {
  STARTING: 11,  // confirmed: 22 entries (11 per team) in test fixture
  SUBSTITUTE: 12 // confirmed: 18 entries (bench players) in test fixture
};

// Team-level statistics, fixture.statistics[].type_id -> type.name, all confirmed
// present in the real response (84 statistic rows across both teams):
const STAT_TYPE_IDS = {
  POSSESSION_PCT: 45,        // "Ball Possession %"
  SHOTS_TOTAL: 42,           // "Shots Total"
  SHOTS_ON_TARGET: 86,       // "Shots On Target"
  SHOTS_OFF_TARGET: 41,      // "Shots Off Target" — returned directly, no need to derive it
  BIG_CHANCES: 580,          // "Big Chances Created" (581 "Big Chances Missed" also exists, not used here)
  CORNERS: 34,               // "Corners"
  OFFSIDES: 51,               // "Offsides"
  FOULS: 56,                 // "Fouls" — one value per team; see foulsPair() below for suffered/committed
  PASSES_TOTAL: 80,          // "Passes"
  PASSES_SUCCESSFUL: 81,     // "Successful Passes"
  PASSES_ACCURACY_PCT: 82,   // "Successful Passes Percentage"
  TACKLES: 78,               // "Tackles"
  DUELS_WON: 106,            // "Duels Won"
  SAVES: 57,                 // "Saves"
  SHOTS_BLOCKED: 58,         // "Shots Blocked" — used for the "blocks" contract field
  THROW_INS: 60,             // "Throwins"
  YELLOW_CARDS: 84,          // "Yellowcards" — team total, distinct from the per-event type_id (19)
  RED_CARDS: 83              // "Redcards" — team total, distinct from the per-event type_id (20)
  // CLEARANCES: confirmed NOT present anywhere in the real statistics response for
  // this fixture/competition on this plan. Left out deliberately — clearances is
  // always returned as null below, never fabricated.
};

// Confirmed present but not currently wired into the Match Hub UI contract — noted
// here in case the stat list is extended later, so they don't need re-discovering:
// Attacks(43), Dangerous Attacks(44), Ball Safe(46), Penalties(47), Shots Insidebox(49),
// Shots Outsidebox(50), Goal Kicks(53), Goal Attempts(54), Free Kicks(55),
// Long Passes(62), Assists(79), Injuries(87), Total Crosses(98), Accurate Crosses(99),
// Interceptions(100), Dribble Attempts(108), Successful Dribbles(109),
// Successful Dribbles %(1605), Successful Long Passes(27264/27265).

// SportMonks' own generic silhouette used when a player has no real photo on file —
// confirmed present in the real response (one bench player had exactly this URL).
// Treated as "no photo" so the Match Hub's own fallback renders instead of SportMonks'
// placeholder image.
const SPORTMONKS_PLACEHOLDER_PHOTO = 'https://cdn.sportmonks.com/images/soccer/placeholder.png';

function findParticipant(participants, location){
  return (participants || []).find(function(p){
    return (p.meta || {}).location === location; // 'home' | 'away'
  }) || null;
}

function statValue(statistics, participantId, typeId){
  var entry = (statistics || []).find(function(s){
    return s.type_id === typeId && s.participant_id === participantId;
  });
  return entry && entry.data ? entry.data.value : null;
}

function statPair(statistics, home, away, typeId){
  return {
    home: statValue(statistics, home && home.id, typeId),
    away: statValue(statistics, away && away.id, typeId)
  };
}

// "Fouls" only exists as one value per team (fouls that team committed). A team's
// fouls *suffered* is the opponent's committed-fouls value — there is no separate
// "suffered" stat on this plan, so it's derived from the same FOULS type_id rather
// than invented.
function foulsPair(statistics, home, away){
  var homeCommitted = statValue(statistics, home && home.id, STAT_TYPE_IDS.FOULS);
  var awayCommitted = statValue(statistics, away && away.id, STAT_TYPE_IDS.FOULS);
  return {
    foulsCommitted: { home: homeCommitted, away: awayCommitted },
    foulsSuffered: { home: awayCommitted, away: homeCommitted }
  };
}

function scoreFor(scores, participantId){
  var entry = (scores || []).find(function(s){
    return s.participant_id === participantId && s.description === 'CURRENT';
  });
  return entry && entry.score ? entry.score.goals : null;
}

function formationFor(formations, location){
  var entry = (formations || []).find(function(f){ return f.location === location; });
  return entry ? entry.formation : null;
}

function eventTypeFor(typeId){
  switch(typeId){
    case EVENT_TYPE_IDS.GOAL: return 'goal';
    case EVENT_TYPE_IDS.YELLOW_CARD: return 'yellow-card';
    case EVENT_TYPE_IDS.RED_CARD: return 'red-card';
    case EVENT_TYPE_IDS.SUBSTITUTION: return 'sub-off';
    default: return null;
  }
}

function eventTitleFor(typeId, typeName){
  switch(typeId){
    case EVENT_TYPE_IDS.GOAL: return 'Goal';
    case EVENT_TYPE_IDS.YELLOW_CARD: return 'Yellow Card';
    case EVENT_TYPE_IDS.RED_CARD: return 'Red Card';
    case EVENT_TYPE_IDS.SUBSTITUTION: return 'Substitution';
    default: return typeName || 'Event'; // falls back to SportMonks' own type name for anything unmapped (e.g. Missed Penalty, VAR Card)
  }
}

function minuteLabel(ev){
  if(ev.minute == null) return '';
  return ev.extra_minute ? (ev.minute + '+' + ev.extra_minute + "'") : (ev.minute + "'");
}

function photoFor(player){
  var path = player && player.image_path;
  if(!path || path === SPORTMONKS_PLACEHOLDER_PHOTO) return null;
  return path;
}

function mapLineupSide(lineups, participantId){
  var players = (lineups || []).filter(function(l){ return l.team_id === participantId; });
  var starters = players.filter(function(l){ return l.type_id === LINEUP_TYPE_IDS.STARTING; });
  var subs = players.filter(function(l){ return l.type_id === LINEUP_TYPE_IDS.SUBSTITUTE; });

  function toPlayer(l){
    return {
      number: l.jersey_number != null ? l.jersey_number : null,
      name: l.player_name || (l.player && l.player.display_name) || '',
      position: (l.position && l.position.name) || null,
      photo: photoFor(l.player),
      _playerId: l.player_id // internal only, used to attach events below, stripped before return
    };
  }

  return {
    startingXI: starters.map(toPlayer),
    substitutes: subs.map(toPlayer)
  };
}

function attachPlayerEvents(side, events, participantId){
  var byPlayerId = {};
  [].concat(side.startingXI, side.substitutes).forEach(function(p){
    if(p._playerId != null) byPlayerId[p._playerId] = p;
  });
  (events || []).forEach(function(ev){
    if(ev.participant_id !== participantId) return;
    var type = eventTypeFor(ev.type_id);
    if(!type) return;
    // Confirmed from the real response: for a Substitution event, `player_id` is the
    // incoming substitute (found in the substitutes lineup, on_bench:false at the
    // moment of the event) and `related_player_id` is the starter leaving the pitch.
    // "sub-off" reads more naturally on the player who left, so use related_player_id
    // for substitutions specifically; every other event type keys off player_id as-is.
    var targetId = (ev.type_id === EVENT_TYPE_IDS.SUBSTITUTION) ? ev.related_player_id : ev.player_id;
    var target = byPlayerId[targetId];
    if(target){
      target.eventTime = minuteLabel(ev);
      target.eventType = type;
    }
  });
}

function stripInternalFields(list){
  return list.map(function(p){
    var copy = {};
    for(var k in p){ if(k !== '_playerId') copy[k] = p[k]; }
    return copy;
  });
}

function mapSportMonksToMatchHub(fixture){
  var participants = fixture.participants || [];
  var home = findParticipant(participants, 'home');
  var away = findParticipant(participants, 'away');
  var statistics = fixture.statistics || [];
  var events = fixture.events || [];
  var scores = fixture.scores || [];
  var formations = fixture.formations || [];

  var homeSide = mapLineupSide(fixture.lineups, home && home.id);
  var awaySide = mapLineupSide(fixture.lineups, away && away.id);
  attachPlayerEvents(homeSide, events, home && home.id);
  attachPlayerEvents(awaySide, events, away && away.id);

  var fouls = foulsPair(statistics, home, away);

  return {
    home: {
      name: home ? home.name : '',
      logo: home ? home.image_path : '',
      score: scoreFor(scores, home && home.id)
    },
    away: {
      name: away ? away.name : '',
      logo: away ? away.image_path : '',
      score: scoreFor(scores, away && away.id)
    },
    competition: fixture.league ? fixture.league.name : '',
    venue: fixture.venue ? fixture.venue.name : '',
    status: fixture.state ? fixture.state.name : null, // e.g. "Full Time", "Not Started"
    possession: statPair(statistics, home, away, STAT_TYPE_IDS.POSSESSION_PCT),
    statistics: {
      shotsOnTarget: statPair(statistics, home, away, STAT_TYPE_IDS.SHOTS_ON_TARGET),
      shotsOffTarget: statPair(statistics, home, away, STAT_TYPE_IDS.SHOTS_OFF_TARGET),
      shots: statPair(statistics, home, away, STAT_TYPE_IDS.SHOTS_TOTAL),
      bigChances: statPair(statistics, home, away, STAT_TYPE_IDS.BIG_CHANCES),
      totalPasses: statPair(statistics, home, away, STAT_TYPE_IDS.PASSES_TOTAL),
      completedPasses: statPair(statistics, home, away, STAT_TYPE_IDS.PASSES_SUCCESSFUL),
      passAccuracy: statPair(statistics, home, away, STAT_TYPE_IDS.PASSES_ACCURACY_PCT),
      tackles: statPair(statistics, home, away, STAT_TYPE_IDS.TACKLES),
      duelsWon: statPair(statistics, home, away, STAT_TYPE_IDS.DUELS_WON),
      corners: statPair(statistics, home, away, STAT_TYPE_IDS.CORNERS),
      offsides: statPair(statistics, home, away, STAT_TYPE_IDS.OFFSIDES),
      foulsSuffered: fouls.foulsSuffered,
      foulsCommitted: fouls.foulsCommitted,
      saves: statPair(statistics, home, away, STAT_TYPE_IDS.SAVES),
      clearances: { home: null, away: null }, // confirmed not available on this plan/competition — never fabricated
      blocks: statPair(statistics, home, away, STAT_TYPE_IDS.SHOTS_BLOCKED),
      throwIns: statPair(statistics, home, away, STAT_TYPE_IDS.THROW_INS),
      yellowCards: statPair(statistics, home, away, STAT_TYPE_IDS.YELLOW_CARDS),
      redCards: statPair(statistics, home, away, STAT_TYPE_IDS.RED_CARDS)
    },
    events: events
      // Keep every event SportMonks returns (goals, cards, subs, missed penalties,
      // VAR cards, anything else) rather than silently dropping unmapped types —
      // unmapped ones just render with SportMonks' own type name as the title.
      .map(function(ev){
        var title = eventTitleFor(ev.type_id, ev.type && ev.type.name);
        var description = ev.player_name ? (title + ' — ' + ev.player_name) : title;
        // Confirmed from the real response: for a Goal event, related_player_name is
        // the assist provider (present on both real goals in the test fixture).
        if(ev.type_id === EVENT_TYPE_IDS.GOAL && ev.related_player_name){
          description += ' (assist: ' + ev.related_player_name + ')';
        }
        return { minute: minuteLabel(ev), title: title, description: description };
      }),
    lineups: {
      home: {
        teamName: home ? home.name : '',
        logo: home ? home.image_path : '',
        formation: formationFor(formations, 'home'),
        manager: null, // requires the `coaches` include, not requested/confirmed in this test — left null rather than guessed
        startingXI: stripInternalFields(homeSide.startingXI),
        substitutes: stripInternalFields(homeSide.substitutes)
      },
      away: {
        teamName: away ? away.name : '',
        logo: away ? away.image_path : '',
        formation: formationFor(formations, 'away'),
        manager: null,
        startingXI: stripInternalFields(awaySide.startingXI),
        substitutes: stripInternalFields(awaySide.substitutes)
      }
    }
  };
}

module.exports = {
  mapSportMonksToMatchHub: mapSportMonksToMatchHub,
  EVENT_TYPE_IDS: EVENT_TYPE_IDS,
  LINEUP_TYPE_IDS: LINEUP_TYPE_IDS,
  STAT_TYPE_IDS: STAT_TYPE_IDS
};
