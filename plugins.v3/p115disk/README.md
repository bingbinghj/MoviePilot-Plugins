# 115 网盘储存（MoviePilot V3）

插件 ID：`P115Disk`，版本 `3.0.5`，要求 MoviePilot >=3.2.12。同步 [DDSRem 原项目](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v3/p115disk) `3.0.4`（`8cc1786`），保留原作者和 [GPL-3.0](LICENSE)。

原版已提供严格查询回执，继续复用其目录解析、下载鉴权、客户端升级和 SHA1 优化。本版仅保留严格回源时跳过正缓存与缺失黑名单、刷新目录映射、通过宿主严格接口降级的修复。确认不存在与无法确认状态分开，普通查询继续复用缓存。

发布格式为 `plugins.v3/`、`package.v3.json`、`pyproject.toml`，Release `P115Disk_v3.0.5` 提供 `p115disk_v3.0.5.zip` 及 SHA256。仅更新 V3。

回归：`python -m unittest test_p115disk_strict_query -v`，使用真实方法及隔离的宿主和网络边界。上游消除上述差异后改用原版，无需继续维护本修复。
