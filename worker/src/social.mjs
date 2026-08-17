import {
  fetchWithTimeout,
  number,
  safeError,
  shanghaiTimestamp,
} from './intelligence-shared.mjs';

const SOCIAL_MCP_URL = 'https://zhiji-ai.xyz/mcp/xhs-douyin';
const SOCIAL_MCP_COOLDOWN_SECONDS = 3600;
const SOCIAL_MCP_COOLDOWN_SLOT = 'v2';

function cooldownKey(toolName) {
  return new Request('https://tin-insight-social.internal/cooldown/' + SOCIAL_MCP_COOLDOWN_SLOT + '/' + toolName, { method: 'GET' });
}

async function activeCooldown(toolName) {
  const cached = await caches.default.match(cooldownKey(toolName));
  return cached ? cached.text() : '';
}

async function rememberChallenge(toolName, detail) {
  if (!/result_status\s*=\s*5|verify_check|风控人机验证挑战/i.test(String(detail || ''))) return;
  await caches.default.put(cooldownKey(toolName), new Response(String(detail), {
    headers: { 'Cache-Control': 'public, s-maxage=' + SOCIAL_MCP_COOLDOWN_SECONDS },
  }));
}

function parseMcpResponse(text, contentType) {
  if (String(contentType || '').toLowerCase().indexOf('text/event-stream') < 0) {
    return JSON.parse(text);
  }
  const events = [];
  String(text).split(String.fromCharCode(10)).forEach(function (line) {
    if (line.indexOf('data:') !== 0) return;
    const payload = line.slice(5).trim();
    if (payload && payload !== '[DONE]') events.push(JSON.parse(payload));
  });
  return events.length ? events[events.length - 1] : null;
}

function parseJsonText(value) {
  const text = String(value || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  try {
    return JSON.parse(text);
  } catch (_) {
    const objectStart = text.indexOf('{');
    const arrayStart = text.indexOf('[');
    const start = objectStart < 0 ? arrayStart : arrayStart < 0 ? objectStart : Math.min(objectStart, arrayStart);
    const end = Math.max(text.lastIndexOf('}'), text.lastIndexOf(']'));
    if (start < 0 || end <= start) throw new Error('remote MCP returned no JSON payload');
    return JSON.parse(text.slice(start, end + 1));
  }
}

function searchItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== 'object') return [];
  const direct = payload.items || payload.notes || payload.results || payload.list;
  if (Array.isArray(direct)) return direct;
  if (payload.data && payload.data !== payload) return searchItems(payload.data);
  return [];
}

async function mcpSearch(env, toolName, keyword) {
  if (!env.XHS_DOUYIN_MCP_TOKEN) throw new Error('XHS_DOUYIN_MCP_TOKEN is not configured');
  const cooldown = await activeCooldown(toolName);
  if (cooldown) throw new Error(toolName + ': 风控冷却中，暂不重复请求；上次错误：' + cooldown);
  const response = await fetchWithTimeout(SOCIAL_MCP_URL, {
    method: 'POST',
    headers: {
      Accept: 'application/json, text/event-stream',
      'Content-Type': 'application/json',
      'User-Agent': 'Tin-Insight-Cloudflare-Worker/1.0',
      'X-MCP-Token': env.XHS_DOUYIN_MCP_TOKEN,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: toolName === 'xhs_search' ? 31 : 32,
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: { keyword: keyword },
      },
    }),
  }, 45000);
  if (!response.ok) throw new Error(toolName + ' HTTP ' + response.status);
  const parsed = parseMcpResponse(await response.text(), response.headers.get('Content-Type'));
  if (!parsed || parsed.error) throw new Error(toolName + ' invalid MCP response');
  const result = parsed.result || {};
  if (result.isError) {
    const detail = (Array.isArray(result.content) ? result.content : []).map(function (item) {
      return item && item.type === 'text' ? String(item.text || '').trim() : '';
    }).filter(Boolean).join(' ');
    await rememberChallenge(toolName, detail);
    throw new Error(toolName + ': ' + (detail || 'remote MCP error'));
  }
  const structured = searchItems(result.structuredContent);
  if (structured.length) return structured;
  const content = Array.isArray(result.content) ? result.content : [];
  let lastError = 'remote MCP returned no usable search items';
  for (let index = content.length - 1; index >= 0; index -= 1) {
    const item = content[index];
    if (!item || item.type !== 'text') continue;
    const text = String(item.text || '').trim();
    if (!text) continue;
    if (/^error:/i.test(text)) {
      await rememberChallenge(toolName, text);
      throw new Error(toolName + ': ' + text);
    }
    try {
      const items = searchItems(parseJsonText(text));
      if (items.length) return items;
    } catch (error) {
      lastError = safeError(error);
    }
  }
  throw new Error(toolName + ': ' + lastError);
}

function timestampDate(value) {
  if (value == null || value === '') return '';
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
  let numeric = Number(value);
  if (!Number.isFinite(numeric)) return '';
  if (numeric < 100000000000) numeric *= 1000;
  const date = new Date(numeric);
  return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : '';
}

function socialTone(text) {
  const positive = ['上涨', '看多', '偏多', '突破', '支撑', '去库', '紧张', '机会', '多单', '反弹', '走强', '涨价', '抢筹', '低位'];
  const negative = ['下跌', '看空', '偏空', '回调', '泡沫', '宽松', '累库', '空单', '风险', '高处不胜寒', '破位', '走弱', '暴跌'];
  const input = String(text || '');
  const positiveCount = positive.filter(function (word) {
    return input.indexOf(word) >= 0;
  }).length;
  const negativeCount = negative.filter(function (word) {
    return input.indexOf(word) >= 0;
  }).length;
  if (positiveCount > negativeCount) return '偏多';
  if (negativeCount > positiveCount) return '偏空';
  return '分歧';
}

function normalizeSocialItem(item, platform) {
  const card = item.note_card || item.note || item.aweme || item;
  const interact = card.interact_info || card.statistics || {};
  const user = card.user || item.user || {};
  const title = String(
    item.title || item.desc || card.display_title || card.title || card.desc || '',
  ).trim();
  if (!title) return null;
  const identifier = item.note_id || item.aweme_id || item.id || card.note_id || card.aweme_id || card.id || '';
  let url = item.url || card.url || item.share_url || card.share_url || '';
  if (!url && identifier && platform === '小红书') {
    url = 'https://www.xiaohongshu.com/explore/' + identifier;
  }
  if (!url && identifier && platform === '抖音') {
    url = 'https://www.douyin.com/video/' + identifier;
  }
  const likes = number(
    item.digg_count != null ? item.digg_count
      : item.liked_count != null ? item.liked_count
        : item.like_count != null ? item.like_count
          : interact.liked_count != null ? interact.liked_count
            : interact.digg_count,
  ) || 0;
  const comments = number(
    item.comment_count != null ? item.comment_count
      : item.comments_count != null ? item.comments_count
        : interact.comment_count != null ? interact.comment_count
          : interact.comments_count,
  ) || 0;
  const created = item.create_time || item.publish_time || item.time || card.create_time || card.publish_time || '';
  return {
    title: title,
    author: String(item.author || item.nickname || card.author || user.nickname || user.name || '未知作者'),
    likes: likes,
    comments: comments,
    url: String(url || ''),
    date: timestampDate(created) || shanghaiTimestamp().slice(0, 10),
    platform: platform,
    tone: socialTone(title),
    raw_time: number(created) || 0,
  };
}

function dedupeSocial(items) {
  const seen = new Set();
  const output = [];
  items.forEach(function (item) {
    if (!item) return;
    const key = item.title.replace(/[\s#，。！？、,.!?]/g, '').toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    output.push(item);
  });
  return output;
}

export async function buildSocialPayload(env, keyword = '沪锡') {
  const definitions = [
    { tool: 'xhs_search', platform: '小红书' },
    { tool: 'douyin_search', platform: '抖音' },
  ];
  const settled = await Promise.allSettled(definitions.map(function (definition) {
    return mcpSearch(env, definition.tool, keyword);
  }));
  const sources = {};
  let combined = [];
  settled.forEach(function (result, index) {
    const definition = definitions[index];
    if (result.status === 'fulfilled') {
      const normalized = result.value.map(function (item) {
        return normalizeSocialItem(item, definition.platform);
      }).filter(Boolean);
      sources[definition.platform] = { ok: true, count: normalized.length };
      combined = combined.concat(normalized);
    } else {
      sources[definition.platform] = { ok: false, count: 0, error: safeError(result.reason) };
    }
  });
  if (!combined.length) {
    const detail = definitions.map(function (definition) {
      const source = sources[definition.platform] || {};
      return definition.platform + '=' + String(source.error || 'unknown error');
    }).join('; ');
    throw new Error('Both Xiaohongshu and Douyin MCP searches failed: ' + detail);
  }
  combined = dedupeSocial(combined);
  combined.sort(function (left, right) {
    return right.raw_time - left.raw_time || (right.likes + right.comments * 2) - (left.likes + left.comments * 2);
  });
  const scores = combined.map(function (item) {
    return Math.log1p(item.likes + item.comments * 2);
  });
  const maximum = Math.max.apply(null, scores.concat([1]));
  const items = combined.slice(0, 12).map(function (item) {
    const clean = Object.assign({}, item);
    delete clean.raw_time;
    clean.heat = Math.max(10, Math.round(Math.log1p(clean.likes + clean.comments * 2) / maximum * 100));
    return clean;
  });
  return {
    updated_at: shanghaiTimestamp(),
    keyword: keyword,
    source: '网络平台远程数据源；15 分钟边缘缓存',
    method: '标题关键词倾向与互动热度代理，不读取或伪造评论正文',
    sources: sources,
    items: items,
  };
}
