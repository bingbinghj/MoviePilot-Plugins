# 小黑盒每日任务

MoviePilot V2 插件，用于执行小黑盒每日签到和脚本支持的每日任务。

参考原项目：

```text
https://github.com/yowiv08/heybox
https://raw.githubusercontent.com/yowiv08/heybox/refs/heads/main/heybox_sign.js
```

## 功能

- 支持多个小黑盒账号。
- 使用 `pkey` 和 `x_xhh_tokenid` Cookie 调用小黑盒 App 接口。
- 执行每日签到。
- 可选执行原脚本支持的每日分享任务：
  - 分享帖子任务 `task_id=1`
  - 分享游戏详情任务 `task_id=19`
  - 分享游戏评论任务 `task_id=31`
- 支持 Cron 定时执行、手动执行一次、远程命令 `/heybox_signin`。
- 可选限时发布内容任务 `task_id=33` 和发表游戏评价任务 `task_id=24`。
- 新任务默认关闭，发布内容和游戏评分可以自行填写。

## 配置

- `启用插件`：开启后注册定时任务。
- `仅运行一次`：保存配置后执行一次，并在执行前自动关闭该开关。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `执行分享任务`：控制每日分享任务；与新增的发帖、评价开关独立。
- `执行限时发帖任务`：默认关闭；开启后向任务下发的主题发布配置的标题、正文，回查结算后删除本次帖子。
- `执行游戏评价任务`：默认关闭；开启后通过 Web 接口提交配置的评价和评分，最多回查 7 次，每次间隔 2 秒，之后删除本次帖子。
- `限时帖子标题` / `限时帖子正文` / `游戏评价内容` / `游戏评分（1至5）`：实际发布的内容和评分。删除帖子不保证撤销评分。
- `Cron 表达式`：默认 `10 9 * * *`。
- `请求超时秒数`、`失败重试次数`、`重试间隔秒数`：控制接口请求。
- `Cookie`：填写小黑盒 Cookie，至少包含：

```text
pkey=xxx;x_xhh_tokenid=xxx;
```

插件会从 `pkey` 解析 `heybox_id`，并用 `pkey` 生成和原脚本一致的 `imei`。

## 加密和上报说明

原脚本里每日任务的 App 接口分两类：

1. 普通接口请求
   - 先请求 `https://hkey.qcciii.com/hkey` 获取 `hkey`、`version`、`build`。
   - 再把 `hkey`、`imei`、`heybox_id`、`nonce`、客户端版本等参数拼到小黑盒接口 URL 上。
   - 用于任务列表、签到状态、帖子流、游戏推荐、评论列表等接口。

2. 加密上报请求
   - 原脚本没有在本地直接加密 App 上报内容，而是把待上报 JSON 发给 `hkey.qcciii.com/hkey`，参数 `mode=report`。
   - hkey 服务返回已经处理好的 `data`、`key`、`sid`、`hkey`。
   - 插件再把这些字段以表单方式 POST 到 `https://data.xiaoheihe.cn`。

本插件按原脚本复刻这个流程。

分享任务实际会上报：

- 帖子浏览时长：`/bbs/app/link/view/time`
  - 上报帖子 `link_id`、浏览时长 `5` 秒、`h_src` 等。
- 分享行为：`/account/data_report/`
  - 上报 `/share/behavior/tap`
  - 上报 `/share/behavior/success`
  - `addition` 中包含 `src`、`plat=WechatSession`，以及对应的 `link_id` 或 `app_id`。

原项目 `report.js` 里还有 Web 端 AES/RSA 加密逻辑，但 `heybox_sign.js` 的每日任务走的是 App 端 `postEncryptedForm`，也就是上面的 hkey report 流程。

游戏评价发帖使用原项目 `signature.js` 的本地 Web hkey 算法，不使用 App hkey 服务，也不走 Web AES/RSA 上报。Web Cookie 保留已有字段，缺失时补充 `x_pkey` 和 `x_heybox_id`。普通限时发帖和删除使用 App 签名。

## 上游同步

同步至 `yowiv08/heybox` 提交 `15f7fb8bffd2f6d58b1e38755002939fc919b055`（2026-10-07）。

- 修复 `maxjia` 解码，支持 `params.topic_id` 和顶层 `topic_id`；游戏评价读取 `app_id`。
- 修复奖励标签：`b9aca51c` 为经验，`c10d89ae` 为 H 币。
- 新增上游限时发帖和游戏评价任务；两者默认关闭，保留现有账号配置。
- 创建内容的请求不自动重试，避免响应不明时重复发帖。
- 回查失败、超时或停用时仍尝试删除本次创建的帖子；删除失败明确显示 `link_id`，不计为整体成功。
- 任务列表返回错误或结构不完整时报告失败，避免误判为任务全部完成。

实现经过离线请求和结算模拟，没有使用真实账号发帖或评分；服务器规则、登录态或签名服务变化仍可能导致任务失败。

## 注意

- Cookie 等同登录态，请只在自己的 MoviePilot 环境中使用。
- 分享任务属于模拟客户端行为，使用前请自行确认小黑盒规则和账号风险。
- 如果任务类型更新，插件会在详情页显示“未支持任务”。

## V2 兼容

版本 `1.1.0` 使用 V2 公开接口，保持原有账号与分享开关；新增任务设置独立保存。Cron 使用宿主配置时区，每次账号执行结束释放 App / Web HTTP 连接。
