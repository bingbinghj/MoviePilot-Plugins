# 插件验证

## 三个 V3 插件

测试加载真实 MoviePilot SDK、事件管理器、动态 FastAPI 路由和隔离 SQLite。外部账号请求、Redis 连接、宿主调度和进程退出使用替身；不访问用户的生产数据库或执行真实签到。

2026-10-21 验证基准：MoviePilot `v3` 分支提交 `453a9568193cb5345828b12b2611c5c2cae296ea`（V3.1.8），Python 3.14.8，依赖由该宿主的 `uv.lock` 安装。14 项测试通过。

最低版本额外验证：MoviePilot `v3.0.0`，提交 `773d8490645e5b7dd3c07a397e6e6d5ac58ef48e`，独立环境安装其锁定依赖。`test_early_host.py` 覆盖三个插件的真实加载、配置和数据持久化、Cron、命令、一次性执行及类型化 API，验证通过。

本地 V3 开发环境运行（PowerShell）：

```powershell
$env:MOVIEPILOT_BACKEND = 'C:\path\to\MoviePilot'
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\path\to\MoviePilot\.venv\Scripts\python.exe' -m unittest discover -s tests/v3 -p test_plugins.py -v
```

在 V3.0.0 开发环境使用相同命令，将测试模式替换为 `-p test_early_host.py`。各版本使用各自的虚拟环境和锁定依赖，不共用解释器环境。

测试包括三个插件的宿主加载、三套市场索引及移除目录检查、配置和数据跨实例持久化、Cron 时区、重复初始化、命令过滤、停止后的事件丢弃、一次性任务复位及取消、API 真实注册与 HTTP 响应、OpenAPI 模型、重载去重、Redis 配置优先级、HTTP/Redis 连接释放及退出线程取消。

已有完整V3开发环境时，也可设置`MOVIEPILOT_BACKEND`为后端源码路径，在该Python环境执行同一unittest命令。V2与V3测试必须使用独立进程，避免同名插件及SDK测试替身相互影响。
