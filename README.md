# MoviePilot-Plugins

个人维护的 MoviePilot 插件仓库，主要用于 MoviePilot V2。

插件仓库地址：

```text
https://github.com/bingbinghj/MoviePilot-Plugins
```

在 MoviePilot 插件市场中添加上面的仓库地址后，刷新插件市场即可安装。

## 插件列表

| 插件 ID | 名称 | 说明 |
| --- | --- | --- |
| `TemoxSignin` | 中国特摄联盟自动登录 | 每天自动登录中国特摄联盟，并处理站点算术验证。 |
| `NewApiCheckin` | New API每日签到 | 支持多个 New API 站点每日签到，可使用系统访问令牌、session 或 Linux.do 已登录 Cookie。 |

## 安装方式

1. 打开 MoviePilot。
2. 进入插件市场或插件仓库配置页面。
3. 添加仓库地址：

```text
https://github.com/bingbinghj/MoviePilot-Plugins
```

4. 刷新插件市场。
5. 搜索插件名称或插件 ID 后安装。

如果刷新后没有显示插件，可以重启 MoviePilot 后再刷新一次。MoviePilot 对插件市场索引存在缓存。

## 中国特摄联盟自动登录

插件 ID：

```text
TemoxSignin
```

功能：

- 自动访问中国特摄联盟登录页。
- 自动处理站点前置算术验证，例如 `3 + 8 + 7 = ?`。
- 支持每天定时执行。
- 支持手动运行一次。
- 支持远程命令 `/temox_signin`。

默认站点地址：

```text
http://bt.temox.com:8080
```

配置项：

- `启用插件`：开启定时任务。
- `仅运行一次`：保存配置后立即执行一次。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `用户名` / `密码`：中国特摄联盟账号密码。
- `Cron 表达式`：默认每天执行一次。
- `安全提问编号` / `安全提问答案`：账号设置了 Discuz 安全提问时填写，未设置保持默认。

## New API每日签到

插件 ID：

```text
NewApiCheckin
```

功能：

- 支持多个 New API 站点。
- 支持多个账号。
- 支持 `system_access_token + api_user`。
- 支持 `cookies.session + api_user`。
- 支持实验性的 `linuxdo_cookies` OAuth。
- 支持每天定时执行。
- 支持手动运行一次。
- 支持远程命令 `/newapi_checkin`。

账号配置示例：

```json
[
  {
    "name": "AnyRouter",
    "provider": "anyrouter",
    "api_user": "123",
    "system_access_token": "sk-xxxxxxxxxxxxxxxx"
  },
  {
    "name": "自定义站点",
    "origin": "https://example.com",
    "api_user": "123",
    "cookies": {
      "session": "new-api-session-value"
    }
  },
  {
    "name": "Linux.do Cookie OAuth",
    "provider": "hotaru",
    "linuxdo_cookies": "_t=linuxdo_session_value"
  }
]
```

常用参数：

- `provider`：使用内置站点配置。
- `origin`：自定义 New API 站点地址。
- `api_user`：New API 用户 ID，通常在浏览器 Local Storage 的 `user.id` 中。
- `system_access_token`：New API 个人设置中生成的系统访问令牌。
- `cookies.session`：New API 站点的 `session` Cookie。
- `linuxdo_cookies`：已登录 Linux.do 的 Cookie 字符串。

特殊站点可覆盖默认接口路径：

```json
{
  "name": "特殊站点",
  "origin": "https://example.com",
  "api_user": "123",
  "system_access_token": "sk-xxx",
  "check_in_path": "/api/user/checkin",
  "user_info_path": "/api/user/self",
  "api_user_key": "new-api-user"
}
```

说明：

只填写 Linux.do 用户名密码的自动浏览器登录没有内置。参考项目依赖 Camoufox/Playwright 处理 Cloudflare 和 OAuth 页面，这类浏览器运行环境不适合直接放进 MoviePilot 后端插件。建议使用 `system_access_token`、`session` 或 `linuxdo_cookies`。

## 兼容结构

当前仓库同时保留两套结构：

```text
package.json
plugins/
package.v2.json
plugins.v2/
```

这样可以兼容仍读取 `package.json` / `plugins/` 的 MoviePilot 版本，也能兼容读取 `package.v2.json` / `plugins.v2/` 的 V2 插件市场逻辑。

## 免责声明

本仓库插件仅用于个人学习和自动化管理。使用前请确认目标站点规则，账号安全和使用后果由使用者自行承担。
