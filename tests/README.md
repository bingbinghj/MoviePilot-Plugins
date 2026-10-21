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

## 小黑盒上游同步测试

`tests/heybox/test_upstream.py` 覆盖 Web 签名与上游 Node.js 固定输入的一致性、奖励标签、`maxjia`、新增开关的默认值和持久化、发帖与评价参数、结算成功/超时、回查异常及删除失败、创建请求禁止自动重试和 Web Cookie。

在上述 V3 开发环境运行：

```powershell
$env:HEYBOX_TEST_GENERATION = 'v3'
& 'C:\path\to\MoviePilot\.venv\Scripts\python.exe' -m unittest discover -s tests/heybox -p test_upstream.py -v
```

将 `HEYBOX_TEST_GENERATION` 改为 `v2` 或 `v1`，以独立进程加载历史目录的实现。2026-10-21 已在 V3.1.8 运行环境验证 V3 实现，以及在 V3.0.0 兼容层环境验证 V2 实现，各 17 项通过。全部请求、发帖、评分和删除均使用替身。

## 特摄联盟实际登录与奖励提示

`tests/temox/test_messages.py` 使用脱敏后的登录响应结构和模拟 Cookie，覆盖脚本中的欢迎提示、转义与嵌套 HTML、实际奖励名称/单位/数值、Cookie 用户与站点校验、无奖励时不生成提示，以及首次奖励 Cookie 在后续页面清除前捕获、再次登录不复用旧奖励。

```powershell
$env:TEMOX_TEST_GENERATION = 'v3'
& 'C:\path\to\MoviePilot\.venv\Scripts\python.exe' -m unittest discover -s tests/temox -p test_messages.py -v
```

改为 `TEMOX_TEST_GENERATION=v2` 可在独立进程验证历史实现。2026-10-22 两组各 12 项通过，V3.1.8 的 14 项宿主合同测试及 V3.0.0 的最低版本检查也通过。实际登录确认欢迎提示可正确读取；当日重复登录没有返回奖励 Cookie，因此每日首登的真实奖励仍待下一次服务器发放时验证。账号密码、登录态 Cookie 和完整页面未写入仓库。
