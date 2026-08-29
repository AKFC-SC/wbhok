// Match Hub API — Cloudflare Worker
//
// GET /api/match/{sportmonksId}
// GET /api/standings              — First Team (Saudi Pro League), unchanged behavior
// GET /api/standings?league_id=N  — any other competition (e.g. U21 Elite League, 3569);
//                                    current season is resolved from SportMonks, never hardcoded
//
// Calls SportMonks server-side (token read from a Worker Secret, never sent to the
// browser) and returns shaped JSON for the Webflow frontend. mapper.js is verified
// against real fixtures 19777719 (completed) and 19779165 (upcoming); standingsMapper.js
// is verified against the real, current Saudi Pro League season (season_id 27951) —
// see each file's header comments for what was confirmed.

import { mapSportMonksToMatchHub } from './mapper.js';
import { mapStandings } from './standingsMapper.js';

// Confirmed working combined include string (2026-08-26) — see mapper.js header.
const INCLUDE =
  'participants;venue;league;state;scores;formations;events.type;' +
  'lineups.player;lineups.position;lineups.details.type;statistics.type';

const STANDINGS_INCLUDE = 'participant;details.type;form';

// Saudi Pro League, season 2026/2027 — confirmed live via SportMonks on 2026-08-27
// (league_id 944 "Pro League"/"SAU PL", season.is_current: true). Overridable via a
// Worker env var so next season's id can be updated without a code redeploy.
const DEFAULT_STANDINGS_SEASON_ID = '27951';

function corsHeaders(env){
  return {
    'Access-Control-Allow-Origin': env.MATCH_HUB_ALLOWED_ORIGIN || '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Content-Type': 'application/json'
  };
}

async function handleMatch(sportmonksId, env, headers){
  if(!/^\d+$/.test(sportmonksId)){
    return new Response(JSON.stringify({ error: 'Invalid fixture id' }), { status: 400, headers });
  }

  const smUrl = `https://api.sportmonks.com/v3/football/fixtures/${sportmonksId}`
    + `?api_token=${env.SPORTSMONKS_API_TOKEN}&include=${encodeURIComponent(INCLUDE)}`;

  let smRes;
  try {
    smRes = await fetch(smUrl);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'SportMonks request failed' }), { status: 502, headers });
  }

  if(!smRes.ok){
    return new Response(JSON.stringify({ error: 'SportMonks request failed', status: smRes.status }), { status: smRes.status, headers });
  }

  const json = await smRes.json();
  if(!json || !json.data){
    return new Response(JSON.stringify({ error: 'Fixture not found' }), { status: 404, headers });
  }

  let shaped;
  try {
    shaped = mapSportMonksToMatchHub(json.data);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Failed to map fixture data' }), { status: 500, headers });
  }

  return new Response(JSON.stringify(shaped), { status: 200, headers });
}

// Resolves the current season id for an arbitrary league, so a non-First-Team
// competition (e.g. U21) never has to assume or hardcode a season — it always
// asks SportMonks what "current" means for that specific league right now.
async function resolveCurrentSeasonId(leagueId, env){
  const smUrl = `https://api.sportmonks.com/v3/football/leagues/${leagueId}`
    + `?api_token=${env.SPORTSMONKS_API_TOKEN}&include=currentseason`;

  let smRes;
  try {
    smRes = await fetch(smUrl);
  } catch (err) {
    return null;
  }
  if(!smRes.ok) return null;

  const json = await smRes.json();
  const seasonId = json && json.data && json.data.currentseason && json.data.currentseason.id;
  return seasonId ? String(seasonId) : null;
}

async function handleStandings(env, headers, leagueId){
  let seasonId;

  if(leagueId){
    seasonId = await resolveCurrentSeasonId(leagueId, env);
    if(!seasonId){
      return new Response(JSON.stringify({ error: 'Could not resolve current season for league', leagueId }), { status: 502, headers });
    }
  } else {
    // Unchanged First Team behavior — same default/env-var season id as before.
    seasonId = env.STANDINGS_SEASON_ID || DEFAULT_STANDINGS_SEASON_ID;
  }

  const smUrl = `https://api.sportmonks.com/v3/football/standings/seasons/${seasonId}`
    + `?api_token=${env.SPORTSMONKS_API_TOKEN}&include=${encodeURIComponent(STANDINGS_INCLUDE)}`;

  let smRes;
  try {
    smRes = await fetch(smUrl);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'SportMonks request failed' }), { status: 502, headers });
  }

  if(!smRes.ok){
    return new Response(JSON.stringify({ error: 'SportMonks request failed', status: smRes.status }), { status: smRes.status, headers });
  }

  const json = await smRes.json();
  if(!json || !Array.isArray(json.data)){
    return new Response(JSON.stringify({ error: 'Standings not found' }), { status: 404, headers });
  }

  let shaped;
  try {
    shaped = mapStandings(json.data);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Failed to map standings data' }), { status: 500, headers });
  }

  return new Response(JSON.stringify({ standings: shaped }), { status: 200, headers });
}

export default {
  async fetch(request, env){
    const headers = corsHeaders(env);

    if(request.method === 'OPTIONS'){
      return new Response(null, { status: 204, headers });
    }

    if(!env.SPORTSMONKS_API_TOKEN){
      return new Response(JSON.stringify({ error: 'SPORTSMONKS_API_TOKEN not configured' }), { status: 500, headers });
    }

    const url = new URL(request.url);

    const matchRoute = url.pathname.match(/^\/api\/match\/([^/]+)\/?$/);
    if(matchRoute){
      return handleMatch(matchRoute[1], env, headers);
    }

    if(url.pathname.replace(/\/$/, '') === '/api/standings'){
      const leagueId = url.searchParams.get('league_id');
      if(leagueId && !/^\d+$/.test(leagueId)){
        return new Response(JSON.stringify({ error: 'Invalid league_id' }), { status: 400, headers });
      }
      return handleStandings(env, headers, leagueId);
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers });
  }
};
