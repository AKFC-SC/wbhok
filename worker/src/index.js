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
import { mapFixtureCore, mapH2H, mapLastFive } from './previewMapper.js';

// Confirmed working combined include string (2026-08-26) — see mapper.js header.
const INCLUDE =
  'participants;venue;league;state;scores;formations;events.type;' +
  'lineups.player;lineups.position;lineups.details.type;statistics.type';

const STANDINGS_INCLUDE = 'participant;details.type;form';

// Saudi Pro League, season 2026/2027 — confirmed live via SportMonks on 2026-08-27
// (league_id 944 "Pro League"/"SAU PL", season.is_current: true). Overridable via a
// Worker env var so next season's id can be updated without a code redeploy.
const DEFAULT_STANDINGS_SEASON_ID = '27951';

// Explicit allowlist, never a blindly reflected Origin. MATCH_HUB_ALLOWED_ORIGINS is a
// comma-separated non-secret var (see wrangler.toml) so origins can be added later
// without a code change. Access-Control-Allow-Origin is only ever set to the exact
// requesting origin when it's in this list — otherwise the header is omitted entirely,
// which is what makes the browser correctly block any origin not on the list. Vary:
// Origin prevents a cached response for one allowed origin from being served to another.
function corsHeaders(request, env){
  const allowedOrigins = (env.MATCH_HUB_ALLOWED_ORIGINS || '')
    .split(',')
    .map(function(o){ return o.trim(); })
    .filter(Boolean);
  const requestOrigin = request.headers.get('Origin');

  const headers = {
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Content-Type': 'application/json',
    'Vary': 'Origin'
  };
  if(requestOrigin && allowedOrigins.indexOf(requestOrigin) !== -1){
    headers['Access-Control-Allow-Origin'] = requestOrigin;
  }
  return headers;
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

// Pre-match (Match Center) endpoint — GET /api/match/{sportmonksId}/preview.
// Entirely additive: a new route on the same Worker, same secret, same CORS
// headers, same fetch-shape-return pattern as handleMatch. Does not change
// handleMatch or its response shape in any way, so Match Hub's existing
// /api/match/{id} behavior is unaffected.
const PREVIEW_INCLUDE = 'participants;venue;league;state;scores';
const H2H_INCLUDE = 'participants;league;scores;state';
const LAST5_INCLUDE = 'participants;league;scores;state';
const LAST5_WINDOW_DAYS = 90; // same chunk size sync.py already uses (confirmed under SportMonks' 100-day /between cap)

async function smGet(path, env){
  const url = `https://api.sportmonks.com/v3/football${path}`
    + (path.indexOf('?') === -1 ? '?' : '&') + `api_token=${env.SPORTSMONKS_API_TOKEN}`;
  const res = await fetch(url);
  if(!res.ok) return null;
  const json = await res.json();
  return json && json.data ? json.data : null;
}

function isoDate(d){ return d.toISOString().slice(0, 10); }

async function fetchLastFiveForTeam(teamId, excludeFixtureId, env){
  const today = new Date();
  const windowStart = new Date(today.getTime() - LAST5_WINDOW_DAYS * 86400000);
  const path = `/fixtures/between/${isoDate(windowStart)}/${isoDate(today)}/${teamId}`
    + `?include=${encodeURIComponent(LAST5_INCLUDE)}`;
  let data;
  try {
    data = await smGet(path, env);
  } catch (err) {
    return [];
  }
  if(!Array.isArray(data)) return [];
  try {
    return mapLastFive(data, teamId, excludeFixtureId);
  } catch (err) {
    return [];
  }
}

async function fetchH2H(homeId, awayId, env){
  if(!homeId || !awayId) return { summary: { homeWins: 0, draws: 0, awayWins: 0 }, meetings: [] };
  let data;
  try {
    data = await smGet(`/fixtures/head-to-head/${homeId}/${awayId}?include=${encodeURIComponent(H2H_INCLUDE)}`, env);
  } catch (err) {
    return { summary: { homeWins: 0, draws: 0, awayWins: 0 }, meetings: [] };
  }
  if(!Array.isArray(data)) return { summary: { homeWins: 0, draws: 0, awayWins: 0 }, meetings: [] };
  try {
    return mapH2H(data, homeId, awayId);
  } catch (err) {
    return { summary: { homeWins: 0, draws: 0, awayWins: 0 }, meetings: [] };
  }
}

async function handlePreview(sportmonksId, env, headers){
  if(!/^\d+$/.test(sportmonksId)){
    return new Response(JSON.stringify({ error: 'Invalid fixture id' }), { status: 400, headers });
  }

  const smUrl = `https://api.sportmonks.com/v3/football/fixtures/${sportmonksId}`
    + `?api_token=${env.SPORTSMONKS_API_TOKEN}&include=${encodeURIComponent(PREVIEW_INCLUDE)}`;

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

  let core;
  try {
    core = mapFixtureCore(json.data);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Failed to map fixture data' }), { status: 500, headers });
  }

  const [h2h, homeForm, awayForm] = await Promise.all([
    fetchH2H(core.home.id, core.away.id, env),
    core.home.id ? fetchLastFiveForTeam(core.home.id, sportmonksId, env) : [],
    core.away.id ? fetchLastFiveForTeam(core.away.id, sportmonksId, env) : []
  ]);

  return new Response(JSON.stringify({
    home: core.home,
    away: core.away,
    competition: core.competition,
    venue: core.venue,
    location: core.location,
    date: core.date,
    kickoffTime: core.kickoffTime,
    status: core.status,
    h2h: h2h,
    form: { home: homeForm, away: awayForm }
  }), { status: 200, headers });
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
    const headers = corsHeaders(request, env);

    if(request.method === 'OPTIONS'){
      return new Response(null, { status: 204, headers });
    }

    if(!env.SPORTSMONKS_API_TOKEN){
      return new Response(JSON.stringify({ error: 'SPORTSMONKS_API_TOKEN not configured' }), { status: 500, headers });
    }

    const url = new URL(request.url);

    const previewRoute = url.pathname.match(/^\/api\/match\/([^/]+)\/preview\/?$/);
    if(previewRoute){
      return handlePreview(previewRoute[1], env, headers);
    }

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
