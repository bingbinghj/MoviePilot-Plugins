# 115 网盘 STRM 助手 3.0.3

本版本由 bingbinghj 于 2026-11-21 修改，基于 DDSRem 的 [MoviePilot-Plugins](https://github.com/DDSRem-Dev/MoviePilot-Plugins) 3.0.2，源码提交为 `3d8c516084c3adcd60b29e24dbcf35fc3effbee7`。沿用 [GPL-3.0](LICENSE) 许可证。

修复 `core/scrape.py`：刮削事件传递当前生成文件的 `file_list`，并设置 `full_scan=false`，避免单集触发整剧入库。沿用上游持久事件防重和洗版处理。更新仅影响之后发送的事件，不会改写已提交到 ETK 的旧整剧任务。

完整源码及对应前端源码：[bingbinghj/MoviePilot-Plugins](https://github.com/bingbinghj/MoviePilot-Plugins)。发布包的界面和依赖 wheel 复用经 SHA256 校验的上游 3.0.2 发布资产，未重新编译。
