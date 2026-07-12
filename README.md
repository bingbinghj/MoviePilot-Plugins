# MoviePilot-Plugins

个人维护的 MoviePilot 插件仓库，主要用于 MoviePilot V2。

维护者：[bingbinghj](https://github.com/bingbinghj)

插件仓库地址：

```text
https://github.com/bingbinghj/MoviePilot-Plugins
```

在 MoviePilot 插件市场中添加上面的仓库地址后，刷新插件市场即可安装。

## 插件列表

| 插件 ID | 名称 | 说明 |
| --- | --- | --- |
| `TemoxSignin` | 中国特摄联盟自动登录 | 每天自动登录中国特摄联盟，并处理站点算术验证。 |
| `NewApiCheckin` | New API每日签到 | 支持多个 New API 站点每日签到，每个站点独立配置 URL、用户 ID 和 Cookie。 |
| `RedisAutoRestart` | Redis异常自动重启 | 检测 Redis 连接异常或自动诊断日志中的 Redis 故障，并自动重启 MoviePilot。 |
| `HeyboxSignin` | 小黑盒每日任务 | 根据小黑盒 App 接口执行每日签到和支持的每日任务。 |
| `ETKScrapeWebhook` | ETK刮削完成通知 | 合并 MoviePilot 重复刮削请求，并在基础刮削完成后通知 ETK。 |

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
- 登录成功通知包含每日登录奖励提示。
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
- 支持点击新增站点，每个站点独立配置。
- 使用 Cookie + New API 用户 ID 认证。
- 支持每天定时执行。
- 支持手动运行一次。
- 支持远程命令 `/newapi_checkin`。

配置页不需要填写 JSON，也不需要按行填写站点。默认显示 1 个站点，点击 `新增站点` 可以继续添加。

常用参数：

- `站点URL`：New API 站点首页地址，例如 `https://example.com`。
- `New API用户ID`：通常在浏览器 Local Storage 的 `user.id` 中。
- `Cookie`：可粘贴 `session=xxx` 或完整 Cookie 字符串。多站点不同 Cookie 时在各自站点卡片内填写。
- `请求超时秒数` / `失败重试次数` / `重试间隔秒数` / `浏览器等待秒数`：用于控制临时性网络失败重试和 CloakBrowser 页面等待。
- `签到方式`：标准站点用 `API签到`；访问页面后赠送额度的站点用 `访问页面触发`；Any Router 这类返回 `var arg1` JS 防护页的站点用 `CloakBrowser访问触发`，路径建议填 `/console`。
- `Authorization Token`、`签到接口路径`、`用户信息路径`：可选，401/404 或接口不标准时按站点单独填写。

排查失败时，插件详情页会显示失败请求的 URL、HTTP 状态、Content-Type 和截断响应正文；MoviePilot 日志中也会记录每个站点的请求过程。

## 小黑盒每日任务

插件 ID：

```text
HeyboxSignin
```

功能：

- 支持多个小黑盒账号。
- 使用 `pkey` 和 `x_xhh_tokenid` Cookie 调用小黑盒 App 接口。
- 支持每日签到。
- 可选执行原脚本支持的分享帖子、分享游戏详情、分享游戏评论任务。
- 支持每天定时执行、手动运行一次和远程命令 `/heybox_signin`。

配置项：

- `执行分享任务`：开启后会执行分享相关每日任务；关闭后只执行签到。
- `Cookie`：至少包含 `pkey=xxx;x_xhh_tokenid=xxx;`。
- `请求超时秒数` / `失败重试次数` / `重试间隔秒数`：用于控制临时性网络失败重试。

加密上报说明：

插件参考原脚本调用 `hkey.qcciii.com` 获取普通接口 `hkey`。分享任务上报时，会把待上报 JSON 通过 `mode=report` 交给 hkey 服务，拿到加密后的 `data/key/sid` 后再提交到 `data.xiaoheihe.cn`。

## Redis异常自动重启

插件 ID：

```text
RedisAutoRestart
```

功能：

- 定时检测 Redis 连接状态。
- 可扫描自动诊断日志中的 `Redis连接失败`。
- 连续失败达到阈值后自动重启 MoviePilot。
- 支持退出进程、自定义命令、只通知不重启三种模式。
- 支持远程命令 `/redis_auto_restart_check`。

默认重启方式是 `退出进程`，需要你的 Docker、systemd 或其他守护方式能自动拉起 MoviePilot。

## ETK刮削完成通知

插件 ID：

```text
ETKScrapeWebhook
```

功能：

- 按媒体根目录合并短时间内重复触发的 `MetadataScrape` 请求。
- 由插件接管并执行 MoviePilot 基础刮削，避免逐集请求重复刮削。
- 验证目标 NFO 已生成后，再通知 ETK 执行后置增强。
- MoviePilot 基础刮削失败或 NFO 输出不完整时不会通知 ETK。
- 将插件刮削日志归档到 `plugins/etkscrapewebhook.log`，并在详情页显示最近 300 行。
- 日志按 5 MB 轮转，保留当前日志和 10 个备份。

配置项：

- `ETK Webhook地址`：例如 `http://emby-toolkit:5257/webhook/moviepilot`。
- `ETK Webhook共享密钥`：与 ETK 中配置的 Emby Webhook 共享密钥一致。
- `合并等待(秒)`：建议保持默认 10 秒。
- `请求超时(秒)` / `失败重试`：控制通知 ETK 时的请求超时和重试次数。

使用本插件时，应避免同时启用多个自动刮削入口和 ETK 实时文件监控，否则可能在 MoviePilot 基础刮削完成前提前触发 ETK。

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
