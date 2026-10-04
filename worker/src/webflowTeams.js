// Server-side Arabic team-name resolution for Match Center/Match Hub, via the
// existing "First Team Club Logos" Webflow CMS collection (id
// 6a9c2ff98dd513bfc472db69), keyed by that collection's own sportsmonks-team-id
// field (confirmed populated for all 19 current SPL teams, alongside a
// name-arabic field). Only ever called when a client request carries
// ?locale=ar — never touched by an English request, so English never depends
// on Webflow CMS availability or latency.
//
// Auth: Authorization: Bearer <token>, read from env.WEBFLOW_API_TOKEN, a
// Worker Secret — never hardcoded, never logged, never echoed in any response.
// This secret does not exist yet; see the deployment report for the exact
// name/scope required. Until it's configured, getTeamArabicNameMap() returns
// { map: null, error: '...' } — a safe no-op, not a thrown error.
//
// Caching: an in-memory (per-isolate) cache first, then Cloudflare's Cache API
// (shared across isolates in the same colo) second, so a normal traffic
// pattern makes at most one real Webflow API call per TEAM_MAP_TTL_MS window
// rather than one per fixture request.

const TEAM_COLLECTION_ID = '6a9c2ff98dd513bfc472db69';
const TEAM_MAP_TTL_MS = 60 * 60 * 1000; // 1 hour — team rosters/names change rarely
const CACHE_KEY_URL = 'https://internal-cache.akfc.worker/team-arabic-name-map';

// Per-isolate memory cache. Cloudflare Workers can recycle isolates at any
// time, so this is a best-effort fast path, not a durability guarantee — the
// Cache API lookup below is the cross-isolate fallback.
var memoryCache = null; // { map, fetchedAt }

async function fetchAllTeamItems(env){
  var items = [];
  var offset = 0;
  var limit = 100;
  var total = Infinity;

  while(items.length < total){
    var url = 'https://api.webflow.com/v2/collections/' + TEAM_COLLECTION_ID
      + '/items?limit=' + limit + '&offset=' + offset;
    var res = await fetch(url, {
      headers: {
        'Authorization': 'Bearer ' + env.WEBFLOW_API_TOKEN,
        'accept-version': '2.0.0'
      }
    });
    if(!res.ok){
      throw new Error('Webflow Team CMS request failed: ' + res.status);
    }
    var json = await res.json();
    if(!json || !Array.isArray(json.items)){
      throw new Error('Unexpected Webflow Team CMS response shape');
    }
    items = items.concat(json.items);
    total = (json.pagination && typeof json.pagination.total === 'number') ? json.pagination.total : items.length;
    offset += limit;
    if(json.items.length === 0) break; // safety net: never loop forever on an unexpected empty page
  }

  return items;
}

// Only items with BOTH a usable sportsmonks-team-id and a populated
// name-arabic are included — an incomplete CMS record is skipped rather than
// guessed at, matching the venue/league/event dictionaries' own rule.
function buildTeamMap(items){
  var map = {};
  (items || []).forEach(function(item){
    var fieldData = item.fieldData || {};
    var teamId = fieldData['sportsmonks-team-id'];
    var arabicName = fieldData['name-arabic'];
    if(!teamId || !arabicName) return;
    map[String(teamId)] = arabicName;
  });
  return map;
}

// Returns { map, error }. map is null only when there is no usable data at
// all (no fresh fetch succeeded and no cache, in-memory or edge, exists yet)
// — callers must treat a null map as "fall back to the existing English
// name," never as a reason to fail the request.
async function getTeamArabicNameMap(env){
  var now = Date.now();

  if(memoryCache && (now - memoryCache.fetchedAt) < TEAM_MAP_TTL_MS){
    return { map: memoryCache.map, error: null };
  }

  try {
    var cache = caches.default;
    var cachedRes = await cache.match(CACHE_KEY_URL);
    if(cachedRes){
      var cachedJson = await cachedRes.json();
      if(cachedJson && typeof cachedJson.fetchedAt === 'number' && (now - cachedJson.fetchedAt) < TEAM_MAP_TTL_MS){
        memoryCache = { map: cachedJson.map, fetchedAt: cachedJson.fetchedAt };
        return { map: cachedJson.map, error: null };
      }
    }
  } catch (err) {
    // Cache API unavailable or malformed cached entry — fall through to a
    // live fetch below; never fatal.
  }

  if(!env.WEBFLOW_API_TOKEN){
    // Secret not configured yet — safe no-op, never throws. Still returns any
    // stale in-memory map this isolate happens to already have.
    return { map: memoryCache ? memoryCache.map : null, error: 'WEBFLOW_API_TOKEN not configured' };
  }

  try {
    var items = await fetchAllTeamItems(env);
    var map = buildTeamMap(items);
    memoryCache = { map: map, fetchedAt: now };
    try {
      var cache2 = caches.default;
      var body = JSON.stringify({ map: map, fetchedAt: now });
      await cache2.put(CACHE_KEY_URL, new Response(body, {
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'max-age=' + Math.floor(TEAM_MAP_TTL_MS / 1000)
        }
      }));
    } catch (err) {
      // Cache write failure is non-fatal — the in-memory cache still serves
      // this isolate for the rest of its lifetime.
    }
    return { map: map, error: null };
  } catch (err) {
    // Live Webflow fetch failed (network error, non-2xx, bad shape). Fall
    // back to a stale in-memory map if this isolate has one, otherwise null.
    // Never throw — the caller degrades to English names instead.
    return { map: memoryCache ? memoryCache.map : null, error: String((err && err.message) || err) };
  }
}

// Looks up teamId in map; returns fallbackName unchanged when map is null,
// teamId is missing, or no entry exists for that id. Never fabricates a
// translation.
function arabicTeamName(teamId, map, fallbackName){
  if(!map || teamId === null || teamId === undefined) return fallbackName;
  var name = map[String(teamId)];
  return name || fallbackName;
}

module.exports = {
  getTeamArabicNameMap: getTeamArabicNameMap,
  arabicTeamName: arabicTeamName
};
