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

## 配置

- `启用插件`：开启后注册定时任务。
- `仅运行一次`：保存配置后立即执行一次，并自动关闭该开关。
- `发送通知`：执行结束后发送 MoviePilot 通知。
- `执行分享任务`：开启后会执行每日分享相关任务；关闭后只做签到。
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

## 注意

- Cookie 等同登录态，请只在自己的 MoviePilot 环境中使用。
- 分享任务属于模拟客户端行为，使用前请自行确认小黑盒规则和账号风险。
- 如果任务类型更新，插件会在详情页显示“未支持任务”。
