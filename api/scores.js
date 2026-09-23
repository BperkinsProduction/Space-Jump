// Global leaderboard API — Vercel serverless function backed by Upstash Redis (REST).
// Zero npm dependencies: talks to Redis over its REST API with fetch.
//
// Setup: in the Vercel dashboard, project -> Storage -> Create Database -> Upstash Redis.
// Vercel injects the connection env vars automatically; both naming schemes are supported.

const LEADERBOARD_KEY = 'cloudhopper:scores';
const META_KEY = 'cloudhopper:meta';
const MAX_NAME_LEN = 12;
const MAX_SANE_SCORE = 50000;
const TOP_N = 25;
const ALLOWED_ANIMALS = ['🦊', '🐱', '🐰', '🐺', '🐼', '🐶'];

// Vercel's "Connect database" dialog can add a custom prefix (e.g. STORAGE_KV_REST_API_URL),
// so match on the suffix rather than an exact name.
function redisConfig() {
  const env = process.env;
  for (const [urlSuffix, tokenSuffix] of [
    ['KV_REST_API_URL', 'KV_REST_API_TOKEN'],
    ['UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN']
  ]) {
    const urlKey = Object.keys(env).sort().find(k => k.endsWith(urlSuffix) && env[k]);
    if (!urlKey) continue;
    const token = env[urlKey.slice(0, -urlSuffix.length) + tokenSuffix];
    if (token) return { url: env[urlKey].replace(/\/+$/, ''), token };
  }
  return null;
}

async function redis(commands) {
  const cfg = redisConfig();
  if (!cfg) throw new Error('no-db');
  const res = await fetch(`${cfg.url}/pipeline`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(commands)
  });
  if (!res.ok) throw new Error(`redis ${res.status}`);
  const out = await res.json();
  const err = out.find(r => r.error);
  if (err) throw new Error(`redis: ${err.error}`);
  return out.map(r => r.result);
}

function cleanName(raw) {
  if (typeof raw !== 'string') return null;
  const name = raw.trim().toUpperCase().replace(/[^A-Z0-9 _\-!.]/g, '').slice(0, MAX_NAME_LEN);
  return name.length >= 1 ? name : null;
}

async function getTop() {
  const [entries, meta] = await redis([
    ['ZRANGE', LEADERBOARD_KEY, '0', String(TOP_N - 1), 'REV', 'WITHSCORES'],
    ['HGETALL', META_KEY]
  ]);
  const metaMap = {};
  if (Array.isArray(meta)) {
    for (let i = 0; i < meta.length; i += 2) metaMap[meta[i]] = meta[i + 1];
  }
  const top = [];
  for (let i = 0; i < entries.length; i += 2) {
    top.push({
      name: entries[i],
      score: Math.round(+entries[i + 1]),
      animal: metaMap[entries[i]] || '🦊'
    });
  }
  return top;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');

  if (!redisConfig()) {
    // Database not provisioned yet — the game falls back to local-only scores.
    return res.status(200).json({ ok: false, offline: true });
  }

  try {
    if (req.method === 'GET') {
      const top = await getTop();
      return res.status(200).json({ ok: true, top });
    }

    if (req.method === 'POST') {
      const body = req.body || {};
      const name = cleanName(body.name);
      const score = Math.round(+body.score);
      const animal = ALLOWED_ANIMALS.includes(body.animal) ? body.animal : '🦊';

      if (!name) return res.status(400).json({ ok: false, error: 'bad name' });
      if (!Number.isFinite(score) || score < 1 || score > MAX_SANE_SCORE) {
        return res.status(400).json({ ok: false, error: 'bad score' });
      }

      // Light per-IP rate limit: 20 submissions/minute
      const ip = (req.headers['x-forwarded-for'] || 'unknown').split(',')[0].trim();
      const [hits] = await redis([['INCR', `cloudhopper:rl:${ip}`]]);
      if (hits === 1) await redis([['EXPIRE', `cloudhopper:rl:${ip}`, '60']]);
      if (hits > 20) return res.status(429).json({ ok: false, error: 'slow down' });

      // GT: only overwrite if this beats the player's existing best
      await redis([
        ['ZADD', LEADERBOARD_KEY, 'GT', String(score), name],
        ['HSET', META_KEY, name, animal]
      ]);
      const [rank] = await redis([['ZREVRANK', LEADERBOARD_KEY, name]]);
      const top = await getTop();
      return res.status(200).json({ ok: true, rank: rank === null ? null : rank + 1, top });
    }

    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ ok: false, error: 'method not allowed' });
  } catch (e) {
    if (e.message === 'no-db') return res.status(200).json({ ok: false, offline: true });
    return res.status(500).json({ ok: false, error: 'server error' });
  }
};
