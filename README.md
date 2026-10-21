# MoviePilot-Plugins

个人维护的 MoviePilot 插件仓库，同时提供 MoviePilot V2 与 V3 独立版本。

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
| `RedisAutoRestart` | Redis异常自动重启 | 检测 Redis 连接异常或自动诊断日志中的 Redis 故障，并自动重启 MoviePilot。 |
| `HeyboxSignin` | 小黑盒每日任务 | 根据小黑盒 App 接口执行每日签到和支持的每日任务。 |

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
- `仅运行一次`：保存配置后执行一次；V3 使用宿主任务接口时约 3 秒后运行。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `用户名` / `密码`：中国特摄联盟账号密码。
- `Cron 表达式`：默认每天执行一次。
- `安全提问编号` / `安全提问答案`：账号设置了 Discuz 安全提问时填写，未设置保持默认。

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

## 兼容结构

当前仓库同时保留三套结构：

```text
package.json
plugins/
package.v2.json
plugins.v2/
package.v3.json
plugins.v3/
```

V2 读取原有索引和目录；V3 使用 `package.v3.json` / `plugins.v3/`。三个保留插件均有独立 V3 实现，旧索引限定为 `>=2.12.0,<3` 并关闭 V3 回退。

## MoviePilot V3 适配

| 插件 | V3 版本 | 适配内容 |
| --- | --- | --- |
| 中国特摄联盟自动登录 | 2.0.0 | 稳定 SDK、明确 API 模型、宿主时区、一次性任务取消和登录连接释放 |
| Redis异常自动重启 | 2.0.0 | V3 缓存配置、手动 URL 优先、重启任务取消、真实重启状态和连接释放 |
| 小黑盒每日任务 | 2.0.0 | 稳定 SDK、账号结果模型、宿主时区、一次性任务取消和账号连接释放 |

V3 使用同一个仓库地址，刷新市场后安装或更新对应插件。账号、配置键和插件 API 的 JSON 字段沿用原有名称。

Cron 使用 MoviePilot 配置的时区。支持一次性任务接口的 V3 宿主会在保存配置约 3 秒后执行“仅运行一次”；早期 V3 宿主直接执行。开关在执行前持久化复位，停用或重载会取消待执行任务。

未手工填写 Redis URL 时，仅在 `CACHE_BACKEND_TYPE=redis` 时读取 `CACHE_BACKEND_URL`。使用 cachetools 时不自动连接默认 Redis 地址。“只通知不重启”及缺少自定义命令时不会记录为已触发重启。

验证使用 MoviePilot V3.1.8 源码、Python 3.14 和宿主锁定依赖，覆盖真实 SDK、临时 SQLite、动态 API 注册、事件重载及资源清理。第三方站点签到和真实进程退出使用替身，未使用账号进行线上签到。运行方法见[测试说明](tests/README.md)。

## 免责声明

本仓库插件仅用于个人学习和自动化管理。使用前请确认目标站点规则，账号安全和使用后果由使用者自行承担。
