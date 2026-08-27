// Match Hub API — Cloudflare Worker
//
// GET /api/match/{sportmonksId}
// GET /api/standings
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

async function handleStandings(env, headers){
  const seasonId = env.STANDINGS_SEASON_ID || DEFAULT_STANDINGS_SEASON_ID;

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
      return handleStandings(env, headers);
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers });
  }
};
