// Match Hub API — Cloudflare Worker
//
// GET /api/match/{sportmonksId}
//
// Calls SportMonks server-side (token read from a Worker Secret, never sent to the
// browser) and returns the shaped Match Hub contract (see ../../contract.md).
// mapper.js is the same file verified against real fixtures 19777719 (completed)
// and 19779165 (upcoming) — see its header comments for what was confirmed.

import { mapSportMonksToMatchHub } from './mapper.js';

// Confirmed working combined include string (2026-08-26) — see mapper.js header.
const INCLUDE =
  'participants;venue;league;state;scores;formations;events.type;' +
  'lineups.player;lineups.position;lineups.details.type;statistics.type';

function corsHeaders(env){
  return {
    'Access-Control-Allow-Origin': env.MATCH_HUB_ALLOWED_ORIGIN || '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Content-Type': 'application/json'
  };
}

export default {
  async fetch(request, env){
    const headers = corsHeaders(env);

    if(request.method === 'OPTIONS'){
      return new Response(null, { status: 204, headers });
    }

    const url = new URL(request.url);
    const match = url.pathname.match(/^\/api\/match\/([^/]+)\/?$/);

    if(!match){
      return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers });
    }

    if(!env.SPORTSMONKS_API_TOKEN){
      return new Response(JSON.stringify({ error: 'SPORTSMONKS_API_TOKEN not configured' }), { status: 500, headers });
    }

    const sportmonksId = match[1];
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
};
