# New API 每日签到

MoviePilot V2 插件，用于对多个 New API 站点执行每日签到。

参考项目：

```text
https://github.com/aceHubert/newapi-ai-check-in
```

## 支持的认证方式

- Cookie + New API 用户 ID，默认方式
- Linux.do 账号密码

Linux.do 账号密码方式会尝试直连登录并完成 OAuth。如果 Linux.do 触发 Cloudflare、二次验证或其它浏览器校验，请改用 Cookie 方式。

Cookie 方式不是天然没有 Cloudflare 验证。它适合你已经在浏览器里通过 Cloudflare 后，把站点 Cookie 一起复制出来的情况；如果站点需要 Cloudflare，请尽量粘贴完整 Cookie，包含 `cf_clearance`。插件会使用 `curl_cffi` 浏览器 TLS 指纹和 `cloudscraper` 回退来兼容这类请求。

## 配置方式

插件配置页不需要填写 JSON。

### Cookie

1. `认证方式` 选择 `Cookie`。
2. 可以填写全局 `New API用户ID` 和 `Cookie`。
3. 在 `站点列表` 中每行填写一个站点。

站点列表格式：

```text
站点A|https://a.example.com
站点B|https://b.example.com
```

如果多个站点使用同一个用户 ID 和 Cookie，只需要在上面的全局输入框填写一次，站点列表写名称和 URL 即可。

如果每个站点使用不同的用户 ID 或 Cookie，在每行后面追加：

```text
站点A|https://a.example.com|123|session=aaa; cf_clearance=xxx
站点B|https://b.example.com|456|session=bbb; cf_clearance=yyy
```

### Linux.do账号密码

1. `认证方式` 选择 `Linux.do账号密码`。
2. 填写 `Linux.do用户名` 和 `Linux.do密码`。
3. 在 `站点列表` 中每行填写一个站点。

站点列表格式：

```text
站点A|https://a.example.com
站点B|https://b.example.com
```

如站点需要手动指定 Linux.do client_id，可在第三列补充：

```text
站点A|https://a.example.com|linuxdo_client_id
```

## 参数获取

- `New API用户ID`：登录 New API 后，在浏览器 Local Storage 的 `user.id` 中获取。
- `Cookie`：浏览器开发者工具 -> Application -> Cookies -> 对应站点的 `session`，也可以粘贴完整 Cookie 字符串。

## Cloudflare 说明

插件参考 NodeSeek 签到插件的轻量方案，优先使用：

```text
curl_cffi
cloudscraper
requests
```

这能解决一类问题：你已经有有效 Cookie 或 `cf_clearance`，但普通 `requests` 因 TLS/浏览器指纹不像真实浏览器而被拦。

它不能无浏览器完成首次 Cloudflare Challenge。首次验证仍需要你在浏览器中完成，然后复制 Cookie。
