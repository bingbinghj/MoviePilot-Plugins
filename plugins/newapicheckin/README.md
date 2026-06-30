# New API 每日签到

MoviePilot V2 插件，用于对多个 New API 站点执行每日签到。

参考项目：

```text
https://github.com/aceHubert/newapi-ai-check-in
```

## 支持的认证方式

- Linux.do 账号密码，默认方式
- Cookie + New API 用户 ID

Linux.do 账号密码方式会尝试直连登录并完成 OAuth。如果 Linux.do 触发 Cloudflare、二次验证或其它浏览器校验，请改用 Cookie 方式。

## 配置方式

插件配置页不需要填写 JSON。

### Linux.do账号密码

1. `认证方式` 选择 `Linux.do账号密码`。
2. 填写 `Linux.do用户名` 和 `Linux.do密码`。
3. 在 `站点列表` 中每行填写一个站点。

站点列表格式：

```text
AnyRouter|anyrouter
Hotaru|hotaru
自定义站点|https://example.com
```

如站点未内置 Linux.do client_id，可在第三列补充：

```text
自定义站点|https://example.com|linuxdo_client_id
```

### Cookie

1. `认证方式` 选择 `Cookie`。
2. 填写 `New API用户ID`。
3. 填写对应站点的 `Cookie`。
4. 在 `站点列表` 中每行填写一个站点。

站点列表格式：

```text
AnyRouter|anyrouter
自定义站点|https://example.com
```

如果每个站点使用不同的用户 ID 或 Cookie，可在每行后面追加：

```text
站点A|https://a.example.com|123|session=aaa
站点B|https://b.example.com|456|session=bbb
```

## 内置站点

`provider` 可使用内置值，也可以直接填写站点 URL。常用内置值：

```text
anyrouter
wong
x666
huan666
kfc
hotaru
elysiver
2020111_xyz
yyds_215_im
freeapi_dgbmc_top
zuodachen_zdc_mom
callxyq_xyz
sorai_me
muyuan_do
925214_xyz
takeapi
thatapi
duckcoding
free-duckcoding
```

## 参数获取

- `New API用户ID`：登录 New API 后，在浏览器 Local Storage 的 `user.id` 中获取。
- `Cookie`：浏览器开发者工具 -> Application -> Cookies -> 对应站点的 `session`，也可以粘贴完整 Cookie 字符串。
