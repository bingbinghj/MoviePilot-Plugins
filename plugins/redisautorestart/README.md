# Redis 异常自动重启

MoviePilot V2 插件，用于检测 Redis 异常并按配置自动重启 MoviePilot。

## 检测方式

插件支持两种检测来源：

- `直接PING Redis`：优先推荐。插件会使用 Redis URL 连接并执行 `PING`。
- `扫描自动诊断日志`：读取指定日志文件末尾内容，匹配 `Redis连接失败` 等关键字。

两种方式可以同时开启。任意一种明确检测到 Redis 异常，就会计入一次失败。

## 重启方式

- `退出进程`：默认方式。插件会让 MoviePilot 当前进程退出，适合 Docker、systemd、群晖套件等有自动重启策略的部署。
- `执行命令`：执行自定义命令，例如 `docker restart moviepilot`。
- `只通知不重启`：只发送通知和记录日志。

## 关键配置

- `Cron 表达式`：默认每 5 分钟检测一次。
- `连续失败阈值`：连续检测到 Redis 异常达到该次数后才触发重启，默认 2。
- `重启冷却分钟`：触发一次重启后，冷却期内不再重复重启，默认 30 分钟。
- `Redis URL`：可留空，插件会尝试读取 MoviePilot 配置；读取不到时建议手动填写。
- `自动诊断日志路径`：启用日志扫描时填写 MoviePilot 日志文件路径。
- `Redis异常关键字`：每行一个，默认匹配 `Redis连接失败` 和 `Redis缓存，异常信息：Redis连接失败`。

## Redis URL 示例

```text
redis://:password@redis:6379/0
redis://redis:6379/0
```

## 注意

如果使用 `退出进程`，必须确认部署环境会自动拉起 MoviePilot；否则进程退出后不会自行恢复。
