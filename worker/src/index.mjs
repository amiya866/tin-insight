import {
  handleIntelligenceRequest,
  runScheduledChecks,
} from './intelligence.mjs';

const ZHIJI_URL = 'https://zhiji-ai.xyz/guan/api/quote';
const SINA_BASE_URL = 'https://hq.sinajs.cn/';
const CACHE_TTL_SECONDS = 15;
const STALE_TTL_SECONDS = 300;
const QUOTE_PROFILES = {
  tin: {
    commodity: 'tin',
    zhijiSymbols: 'SN,AG,CU',
    requiredProduct: 'SN',
    sinaSymbols: 'hf_SND,s_sh000852',
    lmeCode: 'hf_SND',
    lmeSymbol: 'SND',
    lmeName: 'LME 锡',
  },
  zinc: {
    commodity: 'zinc',
    zhijiSymbols: 'ZN',
    requiredProduct: 'ZN',
    sinaSymbols: 'hf_ZSD',
    lmeCode: 'hf_ZSD',
    lmeSymbol: 'ZSD',
    lmeName: 'LME 锌',
  },
};
const ALLOWED_ORIGINS = new Set([
  'https://wangziquan-del.github.io',
]);

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function ratio(numerator, denominator) {
  return numerator != null && denominator ? numerator / denominator : null;
}

function pct(last, reference) {
  return last != null && reference ? (last - reference) / reference * 100 : null;
}

function shanghaiTimestamp(now = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(now).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+08:00`;
}

function allowedOrigin(origin) {
  if (!origin) return null;
  if (ALLOWED_ORIGINS.has(origin)) return origin;
  if (/^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/.test(origin)) return origin;
  return null;
}

function corsHeaders(origin) {
  const allowed = allowedOrigin(origin);
  const headers = {
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
  if (allowed) headers['Access-Control-Allow-Origin'] = allowed;
  return headers;
}

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'X-Content-Type-Options': 'nosniff',
      ...extraHeaders,
    },
  });
}

function withCors(response, origin, cacheStatus) {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(corsHeaders(origin))) headers.set(key, value);
  if (cacheStatus) headers.set('X-Tin-Cache', cacheStatus);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function cacheKey(url, slot) {
  const key = new URL(url.origin);
  key.pathname = `/__tin_cache/${slot}`;
  return new Request(key.toString(), { method: 'GET' });
}

async function fetchZhiji(env, updatedAt, profile) {
  if (!env.ZHIJI_API_KEY) throw new Error('ZHIJI_API_KEY is not configured');
  const url = new URL(ZHIJI_URL);
  url.searchParams.set('symbols', profile.zhijiSymbols);
  const response = await fetch(url, {
    headers: { 'User-Agent': 'Tin Insight Cloudflare Worker', 'X-Guan-Key': env.ZHIJI_API_KEY },
  });
  if (!response.ok) throw new Error(`Zhiji HTTP ${response.status}`);
  const payload = await response.json();
  const rows = payload.quotes || payload.data || [];
  const result = {};
  for (const item of rows) {
    if (item.error) continue;
    const product = String(item.product || item.resolved_from || '').toUpperCase();
    if (!product) continue;
    result[product] = {
      symbol: item.symbol || product,
      name: item.name || product,
      last: number(item.last),
      change_pct: number(item.change_pct),
      time: item.time || null,
      date: updatedAt.slice(0, 10),
      open_interest: number(item.open_interest),
      volume: number(item.volume),
      source: '网络实时行情',
    };
  }
  if (!result[profile.requiredProduct] || result[profile.requiredProduct].last == null) {
    throw new Error(`Zhiji returned no ${profile.requiredProduct} quote`);
  }
  return result;
}

function parseSinaRows(text) {
  const rows = {};
  const quote = String.fromCharCode(34);
  for (const segment of text.split('var hq_str_').slice(1)) {
    const equals = segment.indexOf('=');
    const first = segment.indexOf(quote, equals);
    const last = segment.indexOf(quote, first + 1);
    if (equals > 0 && first > equals && last > first) {
      rows[segment.slice(0, equals)] = segment.slice(first + 1, last).split(',');
    }
  }
  return rows;
}

async function fetchSina(profile) {
  const url = `${SINA_BASE_URL}?rn=${encodeURIComponent(`${profile.commodity}-worker`)}&list=${profile.sinaSymbols}`;
  const response = await fetch(url, {
    headers: {
      Referer: 'https://finance.sina.com.cn/',
      'User-Agent': 'Mozilla/5.0 (Tin Insight Cloudflare Worker)',
    },
  });
  if (!response.ok) throw new Error(`Sina HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  const text = new TextDecoder('gb18030').decode(bytes);
  const rows = parseSinaRows(text);
  const lmeRow = rows[profile.lmeCode];
  const csiRow = rows.s_sh000852;
  const lmeLast = lmeRow && number(lmeRow[0]);
  return {
    lme: lmeLast == null ? null : {
      symbol: profile.lmeSymbol,
      name: lmeRow[13] || profile.lmeName,
      last: lmeLast,
      change_pct: pct(lmeLast, number(lmeRow[7])),
      time: lmeRow[6] || null,
      date: lmeRow[12] || null,
      source: '新浪外盘期货准实时',
    },
    csi1000: csiRow && number(csiRow[1]) != null ? {
      symbol: '000852',
      name: csiRow[0] || '中证1000',
      last: number(csiRow[1]),
      change_pct: number(csiRow[3]),
      time: null,
      date: null,
      source: '新浪中证1000指数',
    } : null,
  };
}

async function buildQuotePayload(env, commodity = 'tin') {
  const profile = QUOTE_PROFILES[commodity];
  if (!profile) throw new Error(`Unsupported commodity: ${commodity}`);
  const updatedAt = shanghaiTimestamp();
  const [zhijiResult, sinaResult] = await Promise.allSettled([
    fetchZhiji(env, updatedAt, profile),
    fetchSina(profile),
  ]);
  if (zhijiResult.status !== 'fulfilled') throw zhijiResult.reason;
  const quotes = zhijiResult.value;
  const market = sinaResult.status === 'fulfilled' ? sinaResult.value : {};
  if (commodity === 'zinc') {
    return {
      updated_at: updatedAt,
      commodity,
      source: '网络实时行情；15 秒边缘缓存',
      zn: quotes.ZN,
      lme: market.lme || null,
    };
  }
  const sn = quotes.SN;
  const ag = quotes.AG || null;
  const cu = quotes.CU || null;
  const csi1000 = market.csi1000 || null;
  return {
    updated_at: updatedAt,
    source: '网络实时行情；15 秒边缘缓存',
    sn,
    lme: market.lme || null,
    ag,
    cu,
    csi1000,
    ratios: {
      tin_silver: { value: ratio(sn.last, ag && ag.last), as_of: updatedAt, source: 'Worker 实时行情' },
      tin_copper: { value: ratio(sn.last, cu && cu.last), as_of: updatedAt, source: 'Worker 实时行情' },
      tin_csi1000: { value: ratio(sn.last, csi1000 && csi1000.last), as_of: updatedAt, source: 'Worker 实时行情' },
    },
  };
}

async function quoteResponse(request, env, ctx) {
  const url = new URL(request.url);
  const commodity = String(url.searchParams.get('commodity') || 'tin').toLowerCase();
  const origin = request.headers.get('Origin');
  if (!QUOTE_PROFILES[commodity]) {
    return withCors(jsonResponse({
      error: 'unsupported_commodity',
      supported: Object.keys(QUOTE_PROFILES),
    }, 400, { 'Cache-Control': 'no-store' }), origin, 'ERROR');
  }
  const cache = caches.default;
  const freshKey = cacheKey(url, `quotes-${commodity}-fresh`);
  const staleKey = cacheKey(url, `quotes-${commodity}-stale`);
  const cached = await cache.match(freshKey);
  if (cached) return withCors(cached, origin, 'HIT');

  try {
    const payload = await buildQuotePayload(env, commodity);
    const fresh = jsonResponse(payload, 200, {
      'Cache-Control': `public, max-age=5, s-maxage=${CACHE_TTL_SECONDS}`,
    });
    const stale = jsonResponse(payload, 200, {
      'Cache-Control': `public, max-age=5, s-maxage=${STALE_TTL_SECONDS}`,
    });
    ctx.waitUntil(Promise.all([
      cache.put(freshKey, fresh.clone()),
      cache.put(staleKey, stale.clone()),
    ]));
    return withCors(fresh, origin, 'MISS');
  } catch (error) {
    const stale = await cache.match(staleKey);
    if (stale) return withCors(stale, origin, 'STALE');
    return withCors(jsonResponse({
      error: 'quote_unavailable',
      message: error instanceof Error ? error.message : String(error),
      updated_at: shanghaiTimestamp(),
    }, 502, { 'Cache-Control': 'no-store' }), origin, 'ERROR');
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    if (request.method !== 'GET') {
      return withCors(jsonResponse({ error: 'method_not_allowed' }, 405), origin);
    }
    const intelligence = await handleIntelligenceRequest(request, env, ctx);
    if (intelligence) return intelligence;
    if (url.pathname === '/health') {
      return withCors(jsonResponse({
        ok: true,
        service: 'tin-insight-api',
        configured: Boolean(env.ZHIJI_API_KEY),
        social_configured: Boolean(env.XHS_DOUYIN_MCP_TOKEN),
        feishu_configured: Boolean(env.FEISHU_WEBHOOK),
        ai_configured: Boolean(env.AI),
        now: shanghaiTimestamp(),
      }, 200, { 'Cache-Control': 'no-store' }), origin);
    }
    if (url.pathname === '/api/quotes' || url.pathname === '/quotes') {
      return quoteResponse(request, env, ctx);
    }
    return withCors(jsonResponse({
      service: 'tin-insight-api',
      endpoints: ['/health', '/api/quotes', '/api/technical', '/api/social', '/api/policy'],
      cache_seconds: CACHE_TTL_SECONDS,
    }, 200, { 'Cache-Control': 'no-store' }), origin);
  },
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runScheduledChecks(env, function () {
      return buildQuotePayload(env);
    }));
  },
};
