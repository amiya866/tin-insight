# 锡息相关

全球锡产业监测台：GitHub Pages 前端 + Cloudflare 常驻 Worker。

## 在线架构

- GitHub Pages：公开网页，推送到 `main` 后自动部署。
- Cloudflare Worker：脱离 Codex 和本地终端常驻运行。
- `/api/quotes`：沪锡、伦锡和比价行情。
- `/api/technical`：新浪真实 15/60 分钟 K + 智辑日 K，计算 MA、MACD、RSI 与区间结构；5 分钟边缘缓存。
- `/api/social`：通过远程 MCP 分别检索小红书和抖音；15 分钟边缘缓存，单渠道失败不影响另一渠道。
- `/api/policy`：美联储、International Tin Association、Alphamin 等 RSS 与锡产业聚合；Workers AI 忠实生成中文标题和中文摘要，保留原文链接；15 分钟边缘缓存。
- Cloudflare Cron：每 15 分钟执行一次行情、技术、社交和政策自检。
- 极端行情 UI：沪锡单日涨幅大于 5% 自动切换“长夜临光”霓虹主题，跌幅大于 5% 自动切换“绿野幻梦”莱茵主题，并强化跳动显示沪锡价格。

网页会优先显示 Worker 的实时结果。接口失败时保留最近一次成功缓存；若缓存也不可用，则继续显示构建时写入的页面快照。

## Worker 配置

`worker/wrangler.toml` 配置了 `*/15 * * * *` 的 Cron Trigger。敏感值只放 Cloudflare Secret，不提交到仓库：

```powershell
npx --yes wrangler@latest secret put ZHIJI_API_KEY --config worker/wrangler.toml
npx --yes wrangler@latest secret put XHS_DOUYIN_MCP_TOKEN --config worker/wrangler.toml
npx --yes wrangler@latest secret put FEISHU_WEBHOOK --config worker/wrangler.toml
# 飞书机器人启用签名校验时再设置：
npx --yes wrangler@latest secret put FEISHU_SIGNING_SECRET --config worker/wrangler.toml
```

飞书告警包含异常组件、上海时间、错误摘要和网站链接；相同错误一小时内去重。可选聚合源短暂失败不会产生噪音告警，核心源或小红书/抖音任一渠道失败会告警。

## 验证与部署

```powershell
node worker/test-worker.mjs
node worker/test-intelligence.mjs
npx --yes wrangler@latest deploy --config worker/wrangler.toml
```

GitHub Actions 仍会定时生成 `quotes.json` 作为后备行情快照。
