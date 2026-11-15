# 115 网盘储存（MoviePilot V3）

插件 ID：`P115Disk`，当前版本 `3.0.4`。使用 `plugins.v3/` 与 `package.v3.json` 发布，依赖清单为 `pyproject.toml`。

源项目：[DDSRem-Dev/MoviePilot-Plugins](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v3/p115disk)，同步基准 `3d8c516`，原作者 DDSRem。保留原源码、作者信息和 [GPL-3.0 许可证](LICENSE)。本仓库在原 `3.0.3` 基础上修复 MP V3 严格查询兼容，不修改 V2。

`3.0.4` 补齐严格查询回执，解决 STRM 助手处理整理完成事件时“存储 115网盘Plus 没有能够确认目标状态的查询提供方”的问题。严格核验重新查询目标与目录路径，避免旧缓存把已经删除或换版的文件当作当前文件；网络、授权或其他无法确认状态的错误继续向宿主报告。普通浏览查询保留缓存。

新回执类型在严格入口调用时才导入，旧宿主不调用该能力时保留原加载路径。没有新回执契约的宿主不能使用严格查询恢复，不通过宽松空值伪造文件缺失。

更新此插件后，MP 可按其持久事件机制继续投递尚未确认的整理完成事件。这里不提供重复移动或复制真实文件的恢复入口，也不改变 STRM 助手的覆盖、身份和后处理校验。

隔离回归：`python3 -m unittest test_p115disk_strict_query.py -v`。测试仅加载真实业务类与替代外部边界，不连接115、不发送通知。
