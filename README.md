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
| `NewApiCheckin` | New API每日签到 | 支持多个 New API 站点每日签到，可选择 Linux.do 账号密码或 Cookie 认证。 |

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
- 支持 Linux.do 账号密码认证，默认方式。
- 支持 Cookie + New API 用户 ID 认证。
- 支持每天定时执行。
- 支持手动运行一次。
- 支持远程命令 `/newapi_checkin`。

配置页不需要填写 JSON。默认选择 `Linux.do账号密码`，填写 Linux.do 用户名、密码和站点列表即可。

站点列表格式：

```text
AnyRouter|anyrouter
Hotaru|hotaru
自定义站点|https://example.com
```

常用参数：

- `认证方式`：选择 `Linux.do账号密码` 或 `Cookie`。
- `Linux.do用户名` / `Linux.do密码`：账号密码模式使用。
- `New API用户ID`：Cookie 方式使用，通常在浏览器 Local Storage 的 `user.id` 中。
- `Cookie`：Cookie 方式使用，可粘贴 `session=xxx` 或完整 Cookie 字符串。

说明：

Linux.do 账号密码方式会尝试直连登录并完成 OAuth。如果 Linux.do 触发 Cloudflare、二次验证或其它浏览器校验，请改用 Cookie 方式。

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
