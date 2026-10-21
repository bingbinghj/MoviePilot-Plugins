# OPPO 云服务任务脚本核查

核查日期：2026-10-21。

结论：脚本语法可运行，但当前实现不能作为可靠的自动完成任务或领取碎片脚本。它访问的任务接口确实出现在 OPPO 官方网页中，不过签名生成、任务状态机、设备行为和风控流程均不完整。没有使用账号执行线上请求，因此没有证据证明它实际获得过奖励。

## 核查来源

- 原脚本：`https://raw.githubusercontent.com/KingJin-web/zy/refs/heads/master/签到本/OPPO云服务任务.py`
- 官方任务页：`https://static-cn01a.ocloud.heytapmobi.com/profit/index.html`
- 官方共享逻辑：`https://ocloud-static-cn01.heytapimage.com/profit/profit-sources/cloud-vui-BVxFrmQq.js`
- 官方任务交互：`https://ocloud-static-cn01.heytapimage.com/profit/profit-sources/index-CtqYvv6D.js`

以上 JS 文件由当日官方 HTML 直接引用。文件名带构建哈希，后续发布可能改变。

## 关键差异

| 检查点 | 原脚本行为 | 官方页面行为 | 影响 |
| --- | --- | --- | --- |
| 请求签名 | 直接复用 `OCLOUD_SIGN`，不计算签名 | 对本次请求体字段排序，并包含 timestamp、nonce、token 及业务字段计算签名 | 新时间戳、不同 taskId 或不同请求体不能继续复用同一签名 |
| 时间戳 | 未配置时每次重新生成，配置时长期复用旧值 | 每次生成当前时间戳和 nonce 并重新签名 | 刷新 sign 或单独改时间戳无法修复跨请求不匹配 |
| 上报事件 | 所有任务固定发送 `FINISH_EVENT` | 读取 `completeConditions[0].eventId`，缺省使用 `START_EVENT`，随后更新条件及记录 ID | 未实现任务阶段变化，不能统一宣告任务完成 |
| 任务资源 | 随机选一项，只保留 id/type/name/ext | 按任务类型选择资源，保留资源数据并附加 `userResourceStatus`，部分任务附带 page/module 信息 | 缺少服务端任务判定所需上下文 |
| 风控 | 静态 WebView 请求头 | report-event 调用 bspWwas 随机签名；明确处理验证码、拒绝、签名无效等状态 | 普通 POST 无法保证通过当前风控 |
| 设备任务 | 没有安装、打开 App、播放视频等实际动作，只等待几秒 | 页面存在安装检测、App 打开、停留时长和多阶段任务处理 | 无法证明完成有设备或时长要求的任务 |
| 奖励验证 | 非空领奖 data 就计为成功，coinAmount 缺失时按 0 处理 | 使用领奖成功状态和 coinAmount，还提供余额及奖励记录查询 | 日志“成功”不一定表示实际入账 |

签名是绑定请求内容的，而不只是“有效期”。即使刚抓到的 sign 尚未过期，把 query-home 的签名用于 report-event 或 grant-award 仍不匹配。官方前端对每次 POST 都重新签名，脚本恰好省略了这一步。

官方任务状态包括 taskStatus 的 `NO_BEGIN / INIT / COMPLETE / AWARD_FAIL / FINISH`，以及 taskActionStatus 的 `INIT / RUNNING / BROWSE / WAIT_REWARD / REWARD_FINISH / DONE` 和第二阶段状态。原脚本只跳过 `COMPLETED / RECEIVED / FINISHED`，没有处理这两组真实状态，也没有优先领取已经进入待领奖阶段的记录。

## 已做的离线验证

原脚本通过 Python AST 语法检查。使用替代 Session 和固定假账号，在没有任何线上请求的情况下复现：

1. 三个端点发送不同业务请求体，但携带相同 sign；按官方签名规则计算的三个签名不同。
2. report-event 被接受但返回 `RUNNING` 时，脚本跳过领奖，完成和获得奖励均为 0。
3. 领奖返回非空对象却没有 coinAmount 时，脚本统计“成功 1”，同时“本次获得碎片 0”。

可复现命令：

```powershell
python tools/review_oppo_cloud.py 'C:\path\to\OPPO云服务任务.py'
```

验证工具只加载函数定义并替换网络调用，不执行原脚本 main，不使用真实 token，不发送任务请求。

## 能确定什么

这些任务接口不是凭空编写的，但接口存在与任务能完成是两回事。当前代码更接近抓包请求重放：尝试查询、直接上报完成、尝试领奖。对只需简单事件的个别任务是否曾有效，需要真实服务端返回和奖励入账记录证明；对安装、注册、视频或多阶段任务，这份脚本没有实现相应行为。

判断真正完成，应同时看到服务端任务状态进入可领奖阶段、grant-award 成功，以及重新查询余额或奖励记录后实际增加。末尾“全部执行完毕”、HTTP 200 或“上报成功”均不足以证明获得奖励。
