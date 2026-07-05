# New API 每日签到

MoviePilot V2 插件，用于对多个 New API 站点执行每日签到。

参考项目：

```text
https://github.com/aceHubert/newapi-ai-check-in
```

## 认证方式

插件仅使用 Cookie + New API 用户 ID。账号密码登录已移除，避免直登验证导致签到不稳定。

## 配置方式

插件配置页不需要填写 JSON，也不需要按行填写站点。

1. 默认显示 `站点 1`。
2. 每个站点单独填写 `站点URL`、`New API用户ID`、`Cookie`。
3. 需要多个站点时点击 `新增站点`。
4. 暂不使用的站点关闭对应的 `启用` 开关即可。

配置页预置 50 个站点槽位，后端只处理已启用且填写了 URL 的站点。

## 参数获取

- `站点URL`：New API 站点首页地址，例如 `https://example.com`。
- `New API用户ID`：登录 New API 后，在浏览器 Local Storage 的 `user.id` 中获取。
- `Cookie`：浏览器开发者工具 -> Application -> Cookies -> 对应站点，可以粘贴 `session=xxx`，也可以粘贴完整 Cookie 字符串。
- `请求超时秒数`：单次请求超时时间。
- `失败重试次数`：网络异常、408、429、5xx 等临时性失败时重试；401/404 不重试。
- `重试间隔秒数`：两次重试之间等待的秒数。
- `签到方式`：默认 `API签到`。如果站点是登录/访问首页时自动赠送额度，改为 `访问页面触发`。
- `访问触发路径`：访问页面触发模式使用，默认 `/`。
- `Authorization Token`：可选。站点返回 `未登录且未提供 access token` 或 Cookie 不稳定时，可填写 New API 后台生成的 system access token；支持裸 token 或 `Bearer xxx`。
- `签到接口路径`：可选，默认 `/api/user/checkin`。站点接口不同或返回 404 时再填写。
- `用户信息路径`：可选，默认 `/api/user/self`。未识别到余额时会继续尝试 `/api/status`、`/api/u/dashboard`、`/api/v1/user/info`、`/api/v1/user`。

## 排查日志

插件会在 MoviePilot 日志中记录每个站点的请求 URL、HTTP 状态、Content-Type 和截断后的响应正文。

插件详情页的最近执行结果也会显示失败请求的响应摘要，便于判断：

- `HTTP 401`：通常是 Cookie 失效、New API 用户 ID 不匹配，或站点要求额外认证头。
- `HTTP 404`：通常是站点签到接口路径不同，或配置的站点 URL 不正确。
- `非 JSON 响应`：通常是返回了登录页、站点验证页、反代错误页或站点前端 HTML。
- `命中站点 JS 防护`：通常需要先在浏览器打开站点并通过验证，再复制包含防护 Cookie 的完整 Cookie。

签到成功会兼容 `success=true`、`status=success`、`ret=1`、`code=0`、`ok=true`，以及 `已签到`、`already`、`重复签到` 等常见已签提示。

Any Router、Agent Router 这类“登录/访问页面后提示签到成功、赠送额度”的站点，建议把 `签到方式` 改为 `访问页面触发`，`访问触发路径` 保持 `/`。
