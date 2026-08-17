import {
  fetchWithTimeout,
  number,
  safeError,
  shanghaiTimestamp,
} from './intelligence-shared.mjs';

const ZHIJI_KLINE_URL = 'https://zhiji-ai.xyz/guan/api/kline';
const SINA_MINUTE_URL = 'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/=/InnerFuturesNewService.getFewMinLine';
const TECHNICAL_PROFILES = {
  tin: { zhiji: 'SN', sina: 'SN0', label: '沪锡' },
  zinc: { zhiji: 'ZN', sina: 'ZN0', label: '沪锌' },
};

function normalizeBar(item) {
  const time = String(item.time || item.date || item.datetime || item.trade_date || item.d || '');
  const open = number(item.open != null ? item.open : item.o);
  const high = number(item.high != null ? item.high : item.h);
  const low = number(item.low != null ? item.low : item.l);
  const close = number(item.close != null ? item.close : item.c);
  if (!time || open == null || high == null || low == null || close == null) return null;
  return {
    time: time,
    open: open,
    high: high,
    low: low,
    close: close,
    volume: number(item.volume != null ? item.volume : item.v),
  };
}

async function fetchKline(env, freq, limit, symbol) {
  if (!env.ZHIJI_API_KEY) throw new Error('ZHIJI_API_KEY is not configured');
  const url = new URL(ZHIJI_KLINE_URL);
  url.searchParams.set('symbol', symbol);
  url.searchParams.set('freq', freq);
  url.searchParams.set('cont', '1');
  url.searchParams.set('limit', String(limit || 320));
  const response = await fetchWithTimeout(url.toString(), {
    headers: { 'User-Agent': 'Tin Insight Cloudflare Worker/1.0', 'X-Guan-Key': env.ZHIJI_API_KEY },
  }, 30000);
  if (!response.ok) throw new Error('Zhiji kline ' + freq + ' HTTP ' + response.status);
  const payload = await response.json();
  const raw = payload.bars || payload.data || [];
  const bars = raw.map(normalizeBar).filter(Boolean);
  bars.sort(function (left, right) {
    return left.time.localeCompare(right.time);
  });
  if (bars.length < 20) throw new Error('Zhiji kline ' + freq + ' returned only ' + bars.length + ' bars');
  return bars.slice(-(limit || 320));
}

async function fetchSinaMinute(period, limit, symbol) {
  const url = new URL(SINA_MINUTE_URL);
  url.searchParams.set('symbol', symbol);
  url.searchParams.set('type', period);
  const response = await fetchWithTimeout(url.toString(), {
    headers: {
      Referer: 'https://finance.sina.com.cn/',
      'User-Agent': 'Tin Insight Cloudflare Worker/1.0',
    },
  }, 30000);
  if (!response.ok) throw new Error('Sina minute ' + period + ' HTTP ' + response.status);
  const text = await response.text();
  const start = text.indexOf('=(');
  const end = text.lastIndexOf(');');
  if (start < 0 || end <= start + 2) throw new Error('Sina minute ' + period + ' returned invalid JSONP');
  const raw = JSON.parse(text.slice(start + 2, end));
  const bars = raw.map(normalizeBar).filter(Boolean);
  bars.sort(function (left, right) {
    return left.time.localeCompare(right.time);
  });
  if (bars.length < 20) throw new Error('Sina minute ' + period + ' returned only ' + bars.length + ' bars');
  return bars.slice(-(limit || 320));
}

function movingAverage(values, period) {
  const output = new Array(values.length).fill(null);
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= period) sum -= values[index - period];
    if (index >= period - 1) output[index] = sum / period;
  }
  return output;
}

function ema(values, period) {
  if (!values.length) return [];
  const factor = 2 / (period + 1);
  const output = [values[0]];
  for (let index = 1; index < values.length; index += 1) {
    output.push(values[index] * factor + output[index - 1] * (1 - factor));
  }
  return output;
}

function macd(values) {
  const fast = ema(values, 12);
  const slow = ema(values, 26);
  const dif = values.map(function (_, index) {
    return fast[index] - slow[index];
  });
  const dea = ema(dif, 9);
  const histogram = dif.map(function (value, index) {
    return (value - dea[index]) * 2;
  });
  return { dif: dif, dea: dea, histogram: histogram };
}

function rsi(values, period) {
  if (values.length <= period) return null;
  let gains = 0;
  let losses = 0;
  for (let index = values.length - period; index < values.length; index += 1) {
    const change = values[index] - values[index - 1];
    if (change > 0) gains += change;
    else losses -= change;
  }
  if (!losses) return 100;
  const relative = (gains / period) / (losses / period);
  return 100 - 100 / (1 + relative);
}

function displayNumber(value) {
  if (value == null || !Number.isFinite(value)) return '—';
  return Math.round(value).toLocaleString('zh-CN');
}

function techCard(frame, bars) {
  const closes = bars.map(function (bar) {
    return bar.close;
  });
  const highs = bars.slice(-20).map(function (bar) {
    return bar.high;
  });
  const lows = bars.slice(-20).map(function (bar) {
    return bar.low;
  });
  const ma5 = movingAverage(closes, 5);
  const ma20 = movingAverage(closes, 20);
  const signals = macd(closes);
  const last = closes.length - 1;
  const price = closes[last];
  const lastMa5 = ma5[last];
  const lastMa20 = ma20[last];
  const lastDif = signals.dif[last];
  const lastDea = signals.dea[last];
  const lastHistogram = signals.histogram[last];
  const lastRsi = rsi(closes, 14);
  const rangeLow = Math.min.apply(null, lows);
  const rangeHigh = Math.max.apply(null, highs);
  const position = rangeHigh === rangeLow ? 0.5 : (price - rangeLow) / (rangeHigh - rangeLow);
  const structure = position >= 0.8 ? '上沿附近' : position <= 0.2 ? '下沿附近' : '区间内部';
  let status = '震荡';
  let tone = 'neutral';
  if (price > lastMa5 && price > lastMa20 && lastHistogram >= 0) {
    status = '偏多';
    tone = 'up';
  } else if (price < lastMa5 && price < lastMa20 && lastHistogram <= 0) {
    status = '偏空';
    tone = 'down';
  }
  return {
    frame: frame,
    status: status,
    tone: tone,
    price: price,
    detail: '道氏/均线：MA5 ' + displayNumber(lastMa5) + '、MA20 ' + displayNumber(lastMa20)
      + '；MACD DIF ' + displayNumber(lastDif) + ' / DEA ' + displayNumber(lastDea)
      + '；RSI14 ' + (lastRsi == null ? '—' : lastRsi.toFixed(1))
      + '；缠论简化结构位于20根区间' + structure
      + '；江恩区间 ' + displayNumber(rangeLow) + '–' + displayNumber(rangeHigh) + '。',
  };
}

function klinePayload(bars) {
  const closes = bars.map(function (bar) {
    return bar.close;
  });
  const periods = [5, 10, 20, 60, 288];
  const mas = {};
  periods.forEach(function (period) {
    mas['MA' + period] = movingAverage(closes, period);
  });
  return {
    labels: bars.map(function (bar) {
      return bar.time;
    }),
    candles: bars.map(function (bar) {
      return { o: bar.open, h: bar.high, l: bar.low, c: bar.close };
    }),
    mas: mas,
  };
}

export async function buildTechnicalPayload(env, commodity = 'tin') {
  const profile = TECHNICAL_PROFILES[commodity] || TECHNICAL_PROFILES.tin;
  const definitions = [
    { freq: '15min', frame: '小级别｜15 分钟', run: function () { return fetchSinaMinute('15', 320, profile.sina); } },
    { freq: '60min', frame: '中级别｜60 分钟', run: function () { return fetchSinaMinute('60', 320, profile.sina); } },
    { freq: 'D', frame: '大级别｜日线', run: function () { return fetchKline(env, 'D', 320, profile.zhiji); } },
  ];
  const settled = await Promise.allSettled(definitions.map(function (definition) {
    return definition.run();
  }));
  const tech = [];
  const errors = {};
  let dailyBars = null;
  settled.forEach(function (result, index) {
    const definition = definitions[index];
    if (result.status === 'fulfilled') {
      tech.push(techCard(definition.frame, result.value));
      if (definition.freq === 'D') dailyBars = result.value;
    } else {
      errors[definition.freq] = safeError(result.reason);
    }
  });
  if (!tech.length) throw new Error('All Zhiji kline frequencies failed');
  if (!dailyBars) {
    const fallback = settled.find(function (result) {
      return result.status === 'fulfilled';
    });
    dailyBars = fallback.value;
  }
  return {
    updated_at: shanghaiTimestamp(),
    source: profile.label + '｜新浪 15/60 分钟 K + 网络日 K；5 分钟边缘缓存',
    commodity: commodity,
    tech: tech,
    kline: klinePayload(dailyBars),
    errors: errors,
  };
}
