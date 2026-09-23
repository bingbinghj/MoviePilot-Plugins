# 插件验证

## ETK 1.0.8

两套旧目录独立验证：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_etkscrapewebhook.py
PYTHONDONTWRITEBYTECODE=1 PLUGIN_TREE=plugins python3 -m unittest discover -s tests -p test_etkscrapewebhook.py
```

每套14项，覆盖51集慢速整理、刮削串行、后续文件合并、旧计时器、精确文件和剧集组保留、NFO验收及日志轮转。

## 全部五个V3插件

使用官方V3镜像中的Python 3.14、真实SDK、事件管理器和媒体DTO，以临时SQLite验证配置及插件数据持久化。测试替换宿主模块调度、外部浏览器、Redis和刮削执行；不访问账号、签到网站或生产服务。

在本仓库目录运行：

```bash
docker run --rm --network none --entrypoint python \
  -e CONFIG_DIR=/tmp/plugin-test-config \
  -e CACHE_BACKEND_TYPE=cachetools \
  -e LOG_LEVEL=WARNING \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/plugins:ro" -w /app \
  jxxghp/moviepilot-v3@sha256:da1f4d293ebf4e8215e57bdb81f109d43262182c3cc00bd8bf05fc9f8cf1d023 \
  -m unittest discover -s /plugins/tests/v3 -p test_plugins.py
```

测试包括全部五个插件的原生加载、版本索引、表单、配置与结果持久化；四个定时插件的Cron、手动命令及“仅运行一次”复位；ETK的来源身份、51集整批等待、原生刮削监听器接管与恢复、日志写入器；New API浏览器上下文释放及Redis的V3缓存配置。

已有完整V3开发环境时，也可设置`MOVIEPILOT_BACKEND`为后端源码路径，在该Python环境执行同一unittest命令。V2与V3测试必须使用独立进程，避免同名插件及SDK测试替身相互影响。
