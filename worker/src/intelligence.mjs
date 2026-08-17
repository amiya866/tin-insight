import {
  cachedJson,
  issueListFromPayload,
  safeError,
  shanghaiTimestamp,
} from './intelligence-shared.mjs';
import { buildTechnicalPayload } from './technical.mjs';
import { buildSocialPayload } from './social.mjs';
import { buildPolicyPayload } from './policy.mjs';

const TECH_TTL_SECONDS = 300;
const INTELLIGENCE_TTL_SECONDS = 900;
const TECH_STALE_SECONDS = 3600;
const INTELLIGENCE_STALE_SECONDS = 21600;
const ALERT_COOLDOWN_SECONDS = 3600;

async function feishuSignature(timestamp, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(String(timestamp) + String.fromCharCode(10) + secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key, new Uint8Array());
  const bytes = new Uint8Array(signed);
  let binary = '';
  bytes.forEach(function (byte) {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

async function sendFeishuAlert(env, issues) {
  if (!env.FEISHU_WEBHOOK) return false;
  const timestamp = Math.floor(Date.now() / 1000);
  const lines = [
    '【锡研究网站告警】',
    '级别：ERROR',
    '时间：' + shanghaiTimestamp(),
    '异常组件：' + issues.map(function (issue) {
      return issue.component;
    }).join('、'),
    '错误详情：',
  ];
  issues.slice(0, 8).forEach(function (issue) {
    lines.push('- ' + issue.component + '：' + safeError(issue.message));
  });
  lines.push('页面：https://wangziquan-del.github.io/tin-insight/');
  const body = {
    msg_type: 'text',
    content: { text: lines.join(String.fromCharCode(10)) },
  };
  if (env.FEISHU_SIGNING_SECRET) {
    body.timestamp = String(timestamp);
    body.sign = await feishuSignature(timestamp, env.FEISHU_SIGNING_SECRET);
  }
  const response = await fetch(env.FEISHU_WEBHOOK, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Feishu webhook HTTP ' + response.status);
  const payload = await response.json().catch(function () {
    return {};
  });
  if (payload.code != null && payload.code !== 0) {
    throw new Error('Feishu webhook code ' + payload.code + ': ' + String(payload.msg || 'unknown'));
  }
  return true;
}

function simpleHash(text) {
  let value = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return (value >>> 0).toString(16);
}

async function notifyWithCooldown(env, issues) {
  if (!env.FEISHU_WEBHOOK || !issues.length) return false;
  const fingerprint = simpleHash(issues.map(function (issue) {
    return issue.component + ':' + safeError(issue.message);
  }).sort().join('|'));
  const key = new Request('https://tin-insight-alert.internal/' + fingerprint, { method: 'GET' });
  const cached = await caches.default.match(key);
  if (cached) return false;
  await sendFeishuAlert(env, issues);
  await caches.default.put(key, new Response('sent', {
    headers: { 'Cache-Control': 'public, s-maxage=' + ALERT_COOLDOWN_SECONDS },
  }));
  return true;
}

export async function runScheduledChecks(env, quoteCheck) {
  const definitions = [
    { name: '实时行情', run: quoteCheck },
    { name: '技术分析', run: function () { return buildTechnicalPayload(env); } },
    { name: '社交情绪', run: function () { return buildSocialPayload(env); } },
    { name: '政策事件', run: function () { return buildPolicyPayload(env); } },
  ];
  const settled = await Promise.allSettled(definitions.map(function (definition) {
    return definition.run();
  }));
  let issues = [];
  settled.forEach(function (result, index) {
    const name = definitions[index].name;
    if (result.status === 'rejected') {
      issues.push({ component: name, message: safeError(result.reason) });
    } else {
      issues = issues.concat(issueListFromPayload(name, result.value || {}));
    }
  });
  if (issues.length) {
    console.error('Tin Insight monitor issues: ' + JSON.stringify(issues));
    const notified = await notifyWithCooldown(env, issues);
    return { ok: false, issues: issues, notified: notified };
  }
  return { ok: true, issues: [], notified: false };
}

export async function handleIntelligenceRequest(request, env, ctx) {
  const url = new URL(request.url);
  if (url.pathname === '/api/technical') {
    const commodity = url.searchParams.get('commodity') === 'zinc' ? 'zinc' : 'tin';
    return cachedJson(request, ctx, 'technical-v2-' + commodity, TECH_TTL_SECONDS, TECH_STALE_SECONDS, function () {
      return buildTechnicalPayload(env, commodity);
    });
  }
  if (url.pathname === '/api/social') {
    const commodity = url.searchParams.get('commodity') === 'zinc' ? 'zinc' : 'tin';
    const keyword = commodity === 'zinc' ? '沪锌' : '沪锡';
    return cachedJson(request, ctx, 'social-remote-v3-' + commodity, INTELLIGENCE_TTL_SECONDS, INTELLIGENCE_STALE_SECONDS, function () {
      return buildSocialPayload(env, keyword);
    });
  }
  if (url.pathname === '/api/policy') {
    return cachedJson(request, ctx, 'policy-zh-v4', INTELLIGENCE_TTL_SECONDS, INTELLIGENCE_STALE_SECONDS, function () {
      return buildPolicyPayload(env);
    });
  }
  return null;
}
