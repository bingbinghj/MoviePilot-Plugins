# MoviePilot-Plugins

个人维护的 MoviePilot 插件仓库，提供 MoviePilot V2、V3 插件；ETK 刮削完成通知与 Emby 302 反向代理另提供 V1 版本。

维护者：[bingbinghj](https://github.com/bingbinghj)

## 插件列表

| 插件 ID | 名称 | 说明 |
| --- | --- | --- |
| `TemoxSignin` | 中国特摄联盟自动登录 | 每天自动登录中国特摄联盟，并处理站点算术验证。 |
| `RedisAutoRestart` | Redis异常自动重启 | 检测 Redis 连接异常或自动诊断日志中的 Redis 故障，并自动重启 MoviePilot。 |
| `HeyboxSignin` | 小黑盒每日任务 | 根据小黑盒 App 接口执行每日签到和支持的每日任务。 |
| `ETKScrapeWebhook` | ETK刮削完成通知 | 合并刮削完成批次，校验 NFO 后通知 emby-toolkit。 |
| `EmbyReverseProxy` | Emby 302 反向代理 | 支持 V1/V2/V3，CD2 挂载媒体源只显示文件名。 |

特摄联盟、Redis 和小黑盒插件的结果摘要显示实际执行时间，新记录按 MoviePilot 配置时区保存；旧记录缺少时间时显示“未知”。三个插件的一次性任务开关统一使用“立即运行一次”。

## 安装方式

1. 打开 MoviePilot，进入插件市场或插件仓库配置页面。
2. 添加仓库地址：

   ```text
   https://github.com/bingbinghj/MoviePilot-Plugins
   ```

3. 刷新插件市场，搜索插件名称或插件 ID 后安装。

如果刷新后没有显示插件，可以重启 MoviePilot 后再刷新一次。MoviePilot 对插件市场索引存在缓存。

## 中国特摄联盟自动登录

插件 ID：`TemoxSignin`

### 功能

- 自动访问中国特摄联盟登录页，并处理前置算术验证，例如 `3 + 8 + 7 = ?`。
- 登录通知读取站点实际欢迎提示和当次每日奖励；没有奖励提示时不补写固定数值。
- 保留本次登录跳转过程中发放的奖励 Cookie，待登录页面提供积分名称和单位后生成提示；支持 Discuz AJAX 欢迎消息。
- 支持每天定时执行、立即运行一次和远程命令 `/temox_signin`。

默认站点地址：`http://bt.temox.com:8080`

### 配置

- `启用插件`：开启定时任务。
- `立即运行一次`：保存配置后执行一次；V3 使用宿主任务接口时约 3 秒后运行。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `用户名` / `密码`：中国特摄联盟账号密码。
- `Cron 表达式`：默认每天执行一次。
- `安全提问编号` / `安全提问答案`：账号设置了 Discuz 安全提问时填写，未设置保持默认。

2026-10-23 首次登录已验证实际奖励 Cookie 与论坛积分标签。每日奖励只取当次登录响应，没有新奖励时不复用之前的提示。V2 版本为 `1.0.4`，V3 版本为 `2.0.3`。

## Redis异常自动重启

插件 ID：`RedisAutoRestart`

### 功能

- 定时检测 Redis 连接状态。
- 可扫描自动诊断日志中的 `Redis连接失败`。
- 连续失败达到阈值后自动重启 MoviePilot。
- 支持退出进程、自定义命令、只通知不重启三种模式。
- 支持远程命令 `/redis_auto_restart_check`。

默认重启方式是 `退出进程`，需要 Docker、systemd 或其他守护方式自动拉起 MoviePilot。

### 配置说明

未手工填写 Redis URL 时，仅在 `CACHE_BACKEND_TYPE=redis` 时读取 `CACHE_BACKEND_URL`。使用 cachetools 时不自动连接默认 Redis 地址。“只通知不重启”及缺少自定义命令时不会记录为已触发重启。

## 小黑盒每日任务

插件 ID：`HeyboxSignin`

### 功能

- 支持多个小黑盒账号，使用账号 Cookie 和真实设备参数调用小黑盒 App 接口。
- 支持每日签到，以及可选的分享帖子、分享游戏详情、分享游戏评论任务。
- 可选执行限时发帖（`task_id=33`）和游戏评价（`task_id=24`），两个开关默认关闭。
- 发布内容、评分可以配置；执行后回查任务状态，并删除本次创建的帖子，删除失败会明确提示帖子 ID。
- 支持每天定时执行、立即运行一次和远程命令 `/heybox_signin`。

### 配置

- `执行分享任务`：控制三个每日分享任务；关闭时仍执行签到，发帖、评价任务由各自开关控制。
- `执行限时发帖任务` / `执行游戏评价任务`：独立控制发帖、评价任务，不受分享开关影响；启用后会实际发布内容或提交评分。
- `限时帖子标题` / `限时帖子正文` / `游戏评价内容` / `游戏评分（1至5）`：发布时使用的内容和评分。删除评价帖子不保证撤销评分。
- `Cookie`：包含 `pkey`、`x_xhh_tokenid`，并附加真实设备的 `imei`、`device_info`、`os_version`、`dw`；`channel` 可省略。旧 Cookie 需要补充这些字段。
- `请求超时秒数` / `失败重试次数` / `重试间隔秒数`：控制读取请求的临时网络失败重试；HTTP、JSON 和业务错误不重复请求，写入操作不自动重试。

设备配置格式见[插件说明](plugins.v2/heyboxsignin/README.md#配置)。

### 加密上报说明

插件参考原脚本调用 `hkey.qcciii.com` 获取普通接口 `hkey` 和 `_rnd`，签名请求携带当前设备的 `os_version`。分享任务上报时，把待上报 JSON 通过 `mode=report` 交给 hkey 服务，拿到加密后的 `data/key/sid` 后再提交到 `data.xiaoheihe.cn`。

游戏评价、限时发帖和删除均使用 App 签名。当前同步基准为上游 `2a405b0`（2026-10-29），补齐 `os_version` / `_rnd`，更新分享上报和评价请求，严格校验任务回查与执行结果。V2 版本为 `1.2.1`，V3 版本为 `2.2.1`。

## ETK 刮削完成通知

插件 ID：`ETKScrapeWebhook`

### 配置

- Webhook 地址：`http://<emby-toolkit地址>:5257/webhook/moviepilot`。
- 共享密钥：填写 emby-toolkit 中的“Emby Webhook共享密钥”。
- 合并等待：建议 10 秒。
- 失败重试：可设为 0。

三个版本使用相同配置字段，MoviePilot 按版本从 `plugins/`、`plugins.v2/` 或 `plugins.v3/` 安装对应实现。

升级到 MoviePilot V3 后，ETK 需更新到 `3.0.4`。若日志仍提示 `MediaChain.scrape_metadata_event` 不存在，表示运行的还是 V2 实现；刷新本仓库插件市场后更新或重新安装 ETK。V3 使用 `ScrapingChain` 入口，V2 目录禁止向 V3 回退。

V1/V2 `1.1.1`、V3 `3.0.4` 将音乐请求交由对应宿主处理，避免音乐日志混入 ETK 独立日志；V3 音乐刮削日志写入 `moviepilot.log`。旧宿主是否支持音乐取决于宿主自身能力，插件不提供音乐刮削实现，历史插件日志不会自动删除。

### 版本差异

| MoviePilot 版本 | 处理方式 |
| --- | --- |
| V1 | 接收原生整理完成事件，合并本批已完成文件；手动影视刮削返回后校验本地 NFO 再通知，音乐请求直接转交宿主。 |
| V2 | 代理 `MetadataScrape`，影视等待整理队列完成并合并文件后执行宿主刮削；其他类型直接转交宿主。停用时恢复原监听器。 |
| V3 | 使用原生 SDK 与 `media_source + media_id + type` 身份，只接管影视；音乐和未知类型交回 MoviePilot。只支持一个启用实例。 |

V1 没有 V2/V3 的整理队列及元数据刮削事件，不接管逐文件刮削，也不等待尚未完成或未入队的文件。手动云端刮削无法本地验证 NFO，不发送完成通知。

### 使用说明

- NFO 不完整时发送失败状态，emby-toolkit 不启动后置增强。
- 保持精确文件范围，避免新增单季扩大为整剧。
- V2/V3 搭配 P115StrmHelper 时，只保留整理监控的 STRM 自动刮削入口，关闭其他重复刮削入口和提前触发 ETK 的实时监控。

## Emby 302 反向代理

插件 ID：`EmbyReverseProxy`，本仓库提供 V1 `1.0.0`、V2 `0.2.7`、V3 `3.0.1` 独立适配版。

基于 [DDSRem 原项目](https://github.com/ddsrem-dev/moviepilot-plugins) 的对应版本实现，保留原项目的 HTTP 隐藏规则、302 重定向、播放、探测和外部播放器功能。

### CD2 媒体源显示

在“媒体源隐藏前缀（每行一个）”中填写：

```text
/cd2/115open
```

该前缀匹配的媒体源只显示完整文件名，例如：

```text
凡人修仙传.A Record of a Mortal's Journey to Immortality.S01E01.2020.2160p.WEB-DL.HDR.H265.AAC.2.0-ADWeb.mp4
```

只修改媒体源详情中的展示文本，实际播放和探测继续使用完整路径。匹配按目录边界进行，`/cd2/115open2` 不会匹配上述规则；多个前缀每行填写一个，最长前缀优先。

HTTP(S) 规则沿用原项目：命中后优先展示并解码 `file_name` 参数，否则展示解码后的剩余路径。CD2 本地文件名按原文显示。

首次使用此适配版，在插件市场选择本仓库的 Emby 302 反向代理，MoviePilot 按主程序版本安装对应实现，配置字段沿用原项目。更多配置见[插件说明](plugins.v3/embyreverseproxy/README.md)。

## 兼容结构

仓库保留三套发布结构：

```text
package.json       plugins/
package.v2.json    plugins.v2/
package.v3.json    plugins.v3/
```

五个插件均提供独立 V2、V3 实现。V1 提供 ETK 与 Emby 302 插件，使用 `package.json` / `plugins/` 中的实现；V3 使用 `package.v3.json` / `plugins.v3/`。

特摄联盟、Redis 和小黑盒插件在默认索引与 V2 索引中限定为 `>=2.12.0,<3`，并关闭 V3 回退。ETK 与 Emby 302 分别声明各版本的兼容范围。

## MoviePilot V3 适配

| 插件 | V3 版本 | 适配内容 |
| --- | --- | --- |
| 中国特摄联盟自动登录 | 2.0.3 | 稳定 SDK、明确 API 模型、宿主时区、一次性任务取消和登录连接释放 |
| Redis异常自动重启 | 2.0.1 | V3 缓存配置、手动 URL 优先、重启任务取消、真实重启状态和连接释放 |
| 小黑盒每日任务 | 2.2.1 | App 签名、设备配置、分享和评价接口，严格校验任务回查；稳定 SDK、类型化 API、任务取消和连接释放 |
| ETK刮削完成通知 | 3.0.4 | 原生 SDK、媒体来源身份、影视批次通知及音乐主日志路由 |
| Emby 302 反向代理 | 3.0.1 | 原生 SDK，CD2 挂载媒体源只显示文件名，沿用原有代理流程 |

V3 使用同一个仓库地址，刷新市场后安装或更新对应插件。账号、配置键和插件 API 的 JSON 字段沿用原有名称。

特摄联盟、Redis 和小黑盒的 Cron 使用 MoviePilot 配置时区。支持一次性任务接口的 V3 宿主在保存配置约 3 秒后执行“立即运行一次”；早期 V3 宿主直接执行。开关在执行前持久化复位，停用或重载会取消待执行任务。

## 免责声明

本仓库插件仅用于个人学习和自动化管理。使用前请确认目标站点规则，账号安全和使用后果由使用者自行承担。
