# New API 每日签到

MoviePilot V2 插件，用于对多个 New API 站点执行每日签到。

参考项目：

```text
https://github.com/aceHubert/newapi-ai-check-in
```

## 支持的认证方式

- `system_access_token` + `api_user`
- `cookies.session` + `api_user`
- `linuxdo_cookies` 实验模式：使用已经登录的 Linux.do Cookie 尝试 OAuth 授权

不直接支持只填写 Linux.do 用户名密码自动登录。参考项目依赖 Camoufox/Playwright 处理 Cloudflare 与 OAuth 页面，MoviePilot 后端插件默认不引入这类浏览器运行环境。

## 账号配置示例

```json
[
  {
    "name": "AnyRouter",
    "provider": "anyrouter",
    "api_user": "123",
    "system_access_token": "sk-xxxxxxxxxxxxxxxx"
  },
  {
    "name": "自定义站点",
    "origin": "https://example.com",
    "api_user": "123",
    "cookies": {
      "session": "new-api-session-value"
    }
  },
  {
    "name": "Linux.do Cookie OAuth",
    "provider": "hotaru",
    "linuxdo_cookies": "_t=linuxdo_session_value"
  }
]
```

`provider` 可使用内置值，也可以直接填写 `origin`。自定义站点一般只需要配置 `origin`，标准路径默认如下：

- 签到接口：`/api/user/checkin`
- 用户信息：`/api/user/self`
- 用户标识请求头：`new-api-user`

特殊站点可以在账号项里覆盖：

```json
{
  "name": "特殊站点",
  "origin": "https://example.com",
  "api_user": "123",
  "system_access_token": "sk-xxx",
  "check_in_path": "/api/user/checkin",
  "user_info_path": "/api/user/self",
  "api_user_key": "new-api-user"
}
```

## 获取参数

- `api_user`：登录 New API 后，在浏览器 Local Storage 的 `user.id` 中获取。
- `system_access_token`：New API 个人设置 -> 账户管理 -> 安全设置 -> 生成令牌。
- `cookies.session`：浏览器开发者工具 -> Application -> Cookies -> 对应站点的 `session`。
