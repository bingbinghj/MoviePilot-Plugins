# ETK刮削完成通知

MoviePilot专用插件。它会按媒体根目录防抖合并重复的 `MetadataScrape`，只执行一次MoviePilot基础刮削；MoviePilot生成NFO并通过输出校验后，再通知ETK执行后置增强。

插件启用时会显式停用MoviePilot原始 `MetadataScrape` 监听器，改由插件监听、合并后直接调用原处理器。停用插件时恢复MoviePilot原监听器。如MoviePilot未生成目标NFO，批次会标记为失败，ETK不会接管。

MoviePilot会把插件调用链产生的内置刮削日志归档到 `plugins/etkscrapewebhook.log`。插件不提供详情页面，也不向主 `moviepilot.log` 复制刮削明细；通过插件卡片右下角菜单的原生“查看日志”打开完整日志界面。

插件会把MoviePilot整理阶段已选定的`episode_group`原样传给ETK；未选定时传递空值，明确表示使用TMDb官方季。ETK不会对MoviePilot批次再猜测、回退或改选其他剧集组。

同一媒体根目录同时收到精确`file_list`和不带文件列表的重复事件时，以精确文件列表为准，避免新增单季被扩大为整剧刮削。

插件日志固定按5MB轮转，保留当前日志和10个备份文件。

## 安装

将 `etkscrapewebhook` 目录复制到MoviePilot的本地插件目录，并重启MoviePilot或重载插件。插件类ID为 `ETKScrapeWebhook`。

配置：

- ETK Webhook地址：`http://<ETK地址>:5257/webhook/moviepilot`
- 共享密钥：与ETK“Emby Webhook共享密钥”相同
- 合并等待：建议10秒

使用本插件时，只保留P115StrmHelper“整理监控”中的“STRM自动刮削”，由本插件把逐集请求合并为一次；关闭增量同步、115生活事件和API STRM中的自动刮削，并关闭MoviePilot手动整理的额外刮削入口。关闭P115StrmHelper的“Emby媒体信息提取”和ETK实时文件监控，避免ETK在MoviePilot完成前提前处理。
