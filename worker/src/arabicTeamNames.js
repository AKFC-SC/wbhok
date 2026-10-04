// Applies Team CMS Arabic-name substitution to the Match Hub and Match Center
// response shapes. Pulled out of index.js into its own module purely so it can
// be exercised directly by tests (index.js is an ES module that only parses
// inside wrangler's bundler; this file stays CommonJS like the other pure
// mapper files, so both wrangler and a plain Node test can load it).
//
// Only ever called by index.js when locale === 'ar' — English requests never
// reach either function here, so English never depends on Webflow CMS.

const { arabicTeamName } = require('./webflowTeams.js');

// Overwrites home/away (and the lineup tab labels, which repeat the same team
// names) with the Arabic name from the Team CMS map when one exists for that
// SportMonks team id. A missing/failed map, or a team id with no CMS entry,
// leaves the existing SportMonks name in place rather than failing the request.
function applyArabicTeamNames(shaped, map){
  if(!map) return;
  if(shaped.home) shaped.home.name = arabicTeamName(shaped.home.id, map, shaped.home.name);
  if(shaped.away) shaped.away.name = arabicTeamName(shaped.away.id, map, shaped.away.name);
  if(shaped.lineups){
    if(shaped.lineups.home) shaped.lineups.home.teamName = arabicTeamName(shaped.home && shaped.home.id, map, shaped.lineups.home.teamName);
    if(shaped.lineups.away) shaped.lineups.away.teamName = arabicTeamName(shaped.away && shaped.away.id, map, shaped.lineups.away.teamName);
  }
}

// Same substitution, but for the preview (Match Center) contract's shape:
// core.home/away, each H2H meeting's homeTeam/awayTeam, and each last-5
// entry's opponent. A team id with no CMS entry (e.g. an opponent outside the
// 19-team SPL roster) keeps its existing SportMonks name — never invented.
function applyArabicTeamNamesToPreview(core, h2h, homeForm, awayForm, map){
  if(!map) return;
  if(core.home) core.home.name = arabicTeamName(core.home.id, map, core.home.name);
  if(core.away) core.away.name = arabicTeamName(core.away.id, map, core.away.name);
  (h2h && h2h.meetings || []).forEach(function(m){
    m.homeTeam = arabicTeamName(m.homeTeamId, map, m.homeTeam);
    m.awayTeam = arabicTeamName(m.awayTeamId, map, m.awayTeam);
  });
  (homeForm || []).forEach(function(m){ m.opponent = arabicTeamName(m.opponentId, map, m.opponent); });
  (awayForm || []).forEach(function(m){ m.opponent = arabicTeamName(m.opponentId, map, m.opponent); });
}

module.exports = {
  applyArabicTeamNames: applyArabicTeamNames,
  applyArabicTeamNamesToPreview: applyArabicTeamNamesToPreview
};
