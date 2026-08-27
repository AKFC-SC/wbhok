// Maps a raw SportMonks /standings/seasons/{id} response (with
// include=participant;details.type;form) into a clean array the Standings
// table can render directly.
//
// Verified against the real, current Saudi Pro League season (season_id 27951,
// league_id 944) on 2026-08-27. Confirmed detail type_ids:
//   129 = Overall Matches Played   130 = Overall Won
//   131 = Overall Draw             132 = Overall Lost
//   133 = Overall Goals Scored     134 = Overall Goals Conceded
// Goal difference is derived (goalsFor - goalsAgainst); SportMonks doesn't
// return it as its own stat. Any stat that isn't present comes back null —
// never fabricated.

function statValue(details, typeId) {
  const entry = (details || []).find((d) => d.type_id === typeId);
  return entry ? entry.value : null;
}

export function mapStandings(rawStandings) {
  return (rawStandings || [])
    .filter((row) => row && row.participant)
    .map((row) => {
      const details = row.details || [];
      const played = statValue(details, 129);
      const won = statValue(details, 130);
      const draw = statValue(details, 131);
      const lost = statValue(details, 132);
      const goalsFor = statValue(details, 133);
      const goalsAgainst = statValue(details, 134);
      const goalDifference =
        goalsFor != null && goalsAgainst != null ? goalsFor - goalsAgainst : null;

      const form = (row.form || [])
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((f) => f.form);

      return {
        position: row.position,
        team: {
          id: row.participant.id,
          name: row.participant.name,
          logo: row.participant.image_path || null
        },
        played,
        won,
        draw,
        lost,
        goalsFor,
        goalsAgainst,
        goalDifference,
        points: row.points,
        form
      };
    })
    .sort((a, b) => a.position - b.position);
}
