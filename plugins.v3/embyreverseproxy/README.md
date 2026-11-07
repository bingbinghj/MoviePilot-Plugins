# Emby 302 反向代理

MoviePilot V3 `3.0.1` 适配版，基于 [DDSRem 原项目](https://github.com/ddsrem-dev/moviepilot-plugins) 提交 `3d8c516084c3adcd60b29e24dbcf35fc3effbee7`。

原项目与本适配版使用 GPL-3.0 许可证，见 [LICENSE](LICENSE)。原作者为 DDSRem，本仓库维护 CD2 媒体源显示适配。

## 配置

- **Emby 地址**：填写实际 Emby 服务地址。
- **代理监听地址 / 端口**：沿用原有设置，默认监听 `0.0.0.0:8099`。
- **媒体源隐藏前缀（每行一个）**：支持原有 HTTP(S) 前缀，以及 CD2 等本地绝对路径前缀。留空关闭隐藏。
- **外部播放器、顶置路径规则**：沿用原项目配置与处理方式。

CD2 示例：

```text
/cd2/115open
```

原媒体源路径：

```text
/cd2/115open/媒体库/国漫/凡人修仙传 (2020) {tmdbid=106449}/Season 01/凡人修仙传.A Record of a Mortal's Journey to Immortality.S01E01.2020.2160p.WEB-DL.HDR.H265.AAC.2.0-ADWeb.mp4
```

媒体源中显示：

```text
凡人修仙传.A Record of a Mortal's Journey to Immortality.S01E01.2020.2160p.WEB-DL.HDR.H265.AAC.2.0-ADWeb.mp4
```

本地路径按目录边界匹配，`/cd2/115open2` 不会匹配 `/cd2/115open`。支持多个前缀，最长前缀优先；中文、空格和文件名中的百分号、问号、井号按原文保留。

HTTP(S) 前缀命中后，仍优先展示并解码 URL 的 `file_name` 参数；没有该参数时显示解码后的剩余路径。

## 播放行为

隐藏只应用于原项目既有的媒体源详情展示响应。实际播放和探测继续使用原始路径；302、路径顶置、直链缓存及外部播放器逻辑沿用原项目。

客户端需通过本插件的代理地址访问 Emby，直接访问原 Emby 端口不会经过展示处理。

首次安装或从 DDSRem 原版切换时，请在插件市场选择 `bingbinghj/MoviePilot-Plugins` 仓库的 Emby 302 反向代理 `3.0.1`。插件 ID 和配置键与原项目一致。
