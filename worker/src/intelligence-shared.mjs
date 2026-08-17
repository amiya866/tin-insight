const ALLOWED_ORIGINS = new Set([
  'https://wangziquan-del.github.io',
]);

export function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function shanghaiTimestamp(now = new Date()) {
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
    }).formatToParts(now).filter(function (part) {
      return part.type !== 'literal';
    }).map(function (part) {
      return [part.type, part.value];
    }),
  );
  return parts.year + '-' + parts.month + '-' + parts.day + 'T' + parts.hour + ':' + parts.minute + ':' + parts.second + '+08:00';
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

function jsonResponse(payload, status, extraHeaders) {
  return new Response(JSON.stringify(payload), {
    status: status || 200,
    headers: Object.assign({
      'Content-Type': 'application/json; charset=utf-8',
      'X-Content-Type-Options': 'nosniff',
    }, extraHeaders || {}),
  });
}

function withCors(response, origin, cacheStatus) {
  const headers = new Headers(response.headers);
  const additions = corsHeaders(origin);
  Object.keys(additions).forEach(function (key) {
    headers.set(key, additions[key]);
  });
  if (cacheStatus) headers.set('X-Tin-Cache', cacheStatus);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: headers,
  });
}

function cacheKey(requestUrl, slot) {
  const url = new URL(requestUrl);
  url.pathname = '/__tin_intelligence_cache/' + slot;
  url.search = '';
  return new Request(url.toString(), { method: 'GET' });
}

export function safeError(error) {
  const raw = error instanceof Error ? error.message : String(error);
  return raw
    .replace(/([?&](?:key|token)=)[^&\s]+/gi, '$1[redacted]')
    .replace(/(\/hook\/)[A-Za-z0-9_-]+/g, '$1[redacted]')
    .slice(0, 360);
}

export async function cachedJson(request, ctx, slot, ttl, staleTtl, builder) {
  const origin = request.headers.get('Origin');
  const cache = caches.default;
  const freshKey = cacheKey(request.url, slot + '-fresh');
  const staleKey = cacheKey(request.url, slot + '-stale');
  const cached = await cache.match(freshKey);
  if (cached) return withCors(cached, origin, 'HIT');
  try {
    const payload = await builder();
    const fresh = jsonResponse(payload, 200, {
      'Cache-Control': 'public, max-age=5, s-maxage=' + ttl,
    });
    const stale = jsonResponse(payload, 200, {
      'Cache-Control': 'public, max-age=5, s-maxage=' + staleTtl,
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
      error: 'intelligence_unavailable',
      message: safeError(error),
      updated_at: shanghaiTimestamp(),
    }, 502, { 'Cache-Control': 'no-store' }), origin, 'ERROR');
  }
}

export async function fetchWithTimeout(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(function () {
    controller.abort();
  }, timeoutMs || 25000);
  try {
    return await fetch(url, Object.assign({}, init || {}, { signal: controller.signal }));
  } finally {
    clearTimeout(timer);
  }
}

export function issueListFromPayload(component, payload) {
  const issues = [];
  Object.keys(payload.errors || {}).forEach(function (name) {
    issues.push({ component: component + '/' + name, message: payload.errors[name] });
  });
  Object.keys(payload.sources || {}).forEach(function (name) {
    const source = payload.sources[name];
    if (!source.ok && !source.optional) {
      issues.push({ component: component + '/' + name, message: source.error || 'source failed' });
    }
  });
  return issues;
}
