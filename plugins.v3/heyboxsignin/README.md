# 小黑盒每日任务

插件页面的结果摘要显示实际执行时间，新记录使用 MoviePilot 配置的时区；旧记录缺少时间时显示“未知”。

MoviePilot V3 插件，用于执行小黑盒每日签到和脚本支持的每日任务。

参考原项目：

```text
https://github.com/yowiv08/heybox
https://raw.githubusercontent.com/yowiv08/heybox/refs/heads/main/heybox_sign.js
```

## 功能

- 支持多个小黑盒账号。
- 使用账号 Cookie 和真实设备参数调用小黑盒 App 接口。
- 执行每日签到。
- 签到等待结算时，通过最终任务列表确认完成；持续等待或接口请求失败会报告失败。
- 可选执行原脚本支持的每日分享任务：
  - 分享帖子任务 `task_id=1`
  - 分享游戏详情任务 `task_id=19`
  - 分享游戏评论任务 `task_id=31`
- 支持 Cron 定时执行、手动执行一次、远程命令 `/heybox_signin`。
- 可选限时发布内容任务 `task_id=33` 和发表游戏评价任务 `task_id=24`。
- 新任务默认关闭，发布内容和游戏评分可以自行填写。

## 配置

- `启用插件`：开启后注册定时任务。
- `立即运行一次`：保存配置后执行一次，并在执行前自动关闭该开关。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `执行分享任务`：控制每日分享任务；与新增的发帖、评价开关独立。
- `执行限时发帖任务`：默认关闭；开启后向任务下发的主题发布配置的标题、正文，回查结算后删除本次帖子。
- `执行游戏评价任务`：默认关闭；开启后通过 App 接口提交配置的评价和评分，最多回查 7 次，每次间隔 2 秒，之后删除本次帖子。
- `限时帖子标题` / `限时帖子正文` / `游戏评价内容` / `游戏评分（1至5）`：实际发布的内容和评分。删除帖子不保证撤销评分。
- `Cron 表达式`：默认 `10 9 * * *`。
- `请求超时秒数`、`失败重试次数`、`重试间隔秒数`：控制接口请求。
- `Cookie`：填写小黑盒 Cookie，至少包含：

```text
pkey=xxx;x_xhh_tokenid=xxx;imei=实际设备标识;device_info=实际设备型号;os_version=16;dw=411;
```

插件从 `pkey` 解析 `heybox_id`。`imei`、`device_info`、`os_version`、`dw` 必须使用当前 App 请求中的真实值，示例中的系统版本与宽度仅表示格式；`channel` 可按抓包值附加，也可省略。iOS 抓包中的 `device_id` 原值填写到 `imei`，不要改写为其他格式。

升级前只有 `pkey` 和 `x_xhh_tokenid` 的旧 Cookie 需要补充这些设备字段。插件保留已有账号和任务开关，但不再生成 IMEI 或套用固定设备；缺少必需字段时会在联网前提示需要补充的字段。

## 加密和上报说明

原脚本里每日任务的 App 接口分两类：

1. 普通接口请求
   - 先请求 `https://hkey.qcciii.com/hkey` 获取 `hkey`、`_rnd`、`version`、`build`，请求携带当前设备的 `os_version`。
   - 再把 `hkey`、`_rnd`、`imei`、`heybox_id`、`nonce`、客户端版本等参数拼到小黑盒接口 URL 上。
   - 用于任务列表、签到状态、帖子流、游戏推荐、评论列表等接口。

2. 加密上报请求
   - 原脚本没有在本地直接加密 App 上报内容，而是把待上报 JSON 发给 `hkey.qcciii.com/hkey`，参数 `mode=report`，同样携带当前设备的 `os_version`。
   - hkey 服务返回已经处理好的 `data`、`key`、`sid`、`hkey`、`_rnd`，插件校验签名时间与请求一致。
   - 插件再把这些字段以表单方式 POST 到 `https://data.xiaoheihe.cn`。

本插件按原脚本复刻这个流程。

分享任务实际会上报：

- 帖子浏览时长：`/bbs/app/link/view/time`
  - 上报帖子 `link_id`、浏览时长 `5` 秒、`h_src` 等。
- 分享行为：`/account/data_report/`
  - 上报 `/share/behavior/tap`
  - 上报 `/share/behavior/success`
  - `addition` 中包含 `src`、`plat=WechatSession`，以及对应的 `link_id` 或 `appid`（游戏详情分享使用 `appid`，不再上报旧的 `app_id` / `h_src`）。

原项目 `report.js` 里还有 Web 端 AES/RSA 加密逻辑，但 `heybox_sign.js` 的每日任务走的是 App 端 `postEncryptedForm`，也就是上面的 hkey report 流程。

游戏评价、限时发帖和删除均使用 App 签名。游戏评价按上游提交 `link_tag=3`、`appid`、`score`、评价正文和 `game_impression_post_type=2`，保留空的 `h_src=` 查询参数；不再拉取主题 ID 或使用 Web 发帖。

## 上游同步

同步至 `yowiv08/heybox` 提交 `2a405b053ec97a0e7204272ea4af97ee025ac9b3`（2026-10-29）。

- 普通签名和加密上报补齐 `os_version`，校验并传递服务返回的 `_rnd`，修复签名服务 HTTP 400。
- 设备字段按账号从 Cookie 读取；`channel` 可省略，旧 Cookie 需补充真实设备字段。
- 同步帖子流参数、推荐游戏解析及游戏详情分享的 `appid` 上报。
- 游戏评价改用 App 接口，保留自定义内容和评分以及结算后清理。
- 校验 H 币数据、核心每日任务和任务状态；回查缺少初始任务时报告失败，执行失败不被后续“已完成”状态覆盖。
- 只对可重试的网络错误重试读取请求；HTTP、JSON、业务错误不重试，发帖、删除和上报不重复提交。
- 保留两种 `topic_id` 位置和奖励标签修复；回查失败、超时或停用后仍清理本次帖子，清理失败显示 `link_id`。

实现经过离线请求和结算模拟，没有使用真实账号发帖或评分；服务器规则、登录态或签名服务变化仍可能导致任务失败。

## 注意

- Cookie 等同登录态，请只在自己的 MoviePilot 环境中使用。
- 分享任务属于模拟客户端行为，使用前请自行确认小黑盒规则和账号风险。
- 如果任务类型更新，插件会在详情页显示“未支持任务”。

## V3 适配

版本 `2.2.1` 使用稳定 SDK，并兼容早期 V3 公开的插件基类入口。账号和配置键沿用原有名称。

- Cron 使用 MoviePilot 的 `TZ` 时区。
- “立即运行一次”在支持宿主一次性任务接口时延迟约 3 秒执行，早期 V3 直接执行；执行前持久化关闭开关。
- 停用或重载取消未执行的一次性任务。
- API 显式声明 Pydantic 响应模型，保留既有 JSON 字段。
- 每个账号执行结束后释放 HTTP 连接。
