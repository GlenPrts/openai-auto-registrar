# IMAP 邮箱配置说明

本文档说明如何配置 IMAP 邮箱用于 OpenAI 自动注册。

## 配置文件

- `config.json` - 实际使用的配置文件
- `config.template.json` - 配置模板（参考用）

## 快速开始

1. 复制配置模板：
   ```bash
   cp config.template.json config.json
   ```

2. 编辑 `config.json`，填入你的信息

## 配置项说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `domain` | string | 注册邮箱的域名后缀，配合 `email_prefix` 生成随机邮箱地址 |
| `imap_host` | string | IMAP 服务器地址 |
| `imap_port` | int | IMAP 端口，通常为 `993` |
| `imap_user` | string | 接收验证码的邮箱账号 |
| `imap_pass` | string | 邮箱的 IMAP 授权码（非登录密码） |
| `imap_auth_mode` | string | IMAP 认证模式：`password`（默认）或 `oauth2` |
| `imap_oauth2_token` | string | OAuth2 Access Token（当 `imap_auth_mode` 为 `oauth2` 时必填） |
| `imap_oauth2_refresh_token` | string | OAuth2 Refresh Token（用于自动刷新 Access Token） |
| `imap_oauth2_token_expires_at` | int | Token 过期时间戳（Unix 时间戳，脚本自动维护） |
| `imap_oauth2_client_id` | string | OAuth2 Client ID（用于自动刷新 Token） |
| `imap_oauth2_client_secret` | string | OAuth2 Client Secret（Azure AD 机密客户端需要） |
| `imap_oauth2_tenant_id` | string | OAuth2 Tenant ID（Azure AD 需要，如 Outlook） |
| `email_prefix` | string | 注册邮箱前缀，生成格式为 `{prefix}{uuid}@domain` |

## 认证模式

### Password 模式（默认）

适用于 Gmail、QQ 邮箱等支持 IMAP 密码认证的服务。

配置示例：
```json
{
    "domain": "yourdomain.com",
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "imap_user": "your_email@gmail.com",
    "imap_pass": "your_app_password",
    "imap_auth_mode": "password",
    "email_prefix": "auto"
}
```

**注意**：
- Gmail 需要使用应用专用密码（App Password），不是登录密码
- 在 Google 账户设置中开启两步验证后，才能创建应用专用密码

### OAuth2 模式

适用于 Outlook/Hotmail/Microsoft 365 等使用 OAuth2 认证的服务。

#### Outlook OAuth2 配置步骤

1. 在 `config.json` 中填写基础信息：
   ```json
   {
       "domain": "yourdomain.onmicrosoft.com",
       "imap_host": "outlook.office365.com",
       "imap_port": 993,
       "imap_user": "admin@yourdomain.onmicrosoft.com",
       "imap_pass": "",
       "imap_auth_mode": "oauth2",
       "email_prefix": "user"
   }
   ```

2. 获取 OAuth2 Token：
   ```bash
   uv run python get_outlook_token.py
   ```

   此脚本会：
   - 启动本地回调服务器
   - 打开浏览器让你登录授权
   - 自动提取 authorization code
   - 换取 access_token 和 refresh_token
   - 自动更新 `config.json`

3. 配置文件将被自动更新为：
   ```json
   {
       "imap_oauth2_token": "eyJ0eXAiOiJKV1Qi...",
       "imap_oauth2_refresh_token": "0.AAUA...",
       "imap_oauth2_token_expires_at": 1704067200,
       "imap_oauth2_client_id": "your-client-id",
       "imap_oauth2_client_secret": "your-client-secret",
       "imap_oauth2_tenant_id": "your-tenant-id"
   }
   ```

#### 手动获取 Outlook Token（备选）

如需手动配置：

1. 访问 [Azure Portal](https://portal.azure.com/) → Microsoft Entra ID → 应用注册
2. 创建新应用，支持账户类型选择 "任何组织目录中的帐户和个人 Microsoft 帐户"
3. 添加 API 权限：`IMAP.AccessAsUser.All` 和 `offline_access`
4. 配置平台：添加 "移动和桌面应用程序"，重定向 URI 设为 `http://localhost`
5. 如为机密客户端，创建 **Client Secret**
6. 使用授权 URL 获取 code：
   ```
   https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?
   client_id={client_id}&response_type=code&redirect_uri=http://localhost
   &scope=https://outlook.office.com/IMAP.AccessAsUser.All offline_access
   ```
7. 用 code 换取 token：
   ```bash
   curl -X POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token \
     -d "grant_type=authorization_code" \
     -d "client_id={client_id}" \
     -d "client_secret={client_secret}" \
     -d "code={code}" \
     -d "redirect_uri=http://localhost" \
     -d "scope=https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
   ```

## 使用 IMAP 模式运行

### 命令行

```bash
# 使用 IMAP 配置邮箱
uv run python singup.py --email-mode imap --once

# 使用 IMAP + 代理
uv run python singup.py --email-mode imap --proxy http://127.0.0.1:7890
```

### Web 面板

```bash
uv run python app.py
```

然后在网页界面选择 "IMAP 配置邮箱" 模式并启动服务。

## 辅助脚本

- `get_outlook_token.py` - 自动获取 Outlook OAuth2 Token
- `test_outlook_oauth2.py` - 测试 IMAP OAuth2 配置

## 常见问题

**Q: 如何测试 IMAP 配置是否正确？**

A: 运行测试脚本：
```bash
uv run python test_outlook_oauth2.py
```

**Q: Token 过期了怎么办？**

A: 脚本会自动刷新 Token。如需手动刷新，重新运行：
```bash
uv run python get_outlook_token.py
```

**Q: 提示 `invalid_client` 错误（AADSTS7000218）？**

A: Azure AD 应用配置为机密客户端，需要提供 `client_secret`：
1. 在 Azure Portal 中创建 **Client Secret**
2. 将 `imap_oauth2_client_secret` 填入 `config.json`
3. 或在身份验证 → 高级设置中，将**允许公共客户端流**设为**是**

**Q: Gmail OAuth2 如何配置？**

A: 
1. [Google Cloud Console](https://console.cloud.google.com/) 创建 OAuth2 凭证（Desktop 应用类型）
2. 启用 Gmail API
3. Scope 使用 `https://mail.google.com/` 和 `offline_access`
4. Gmail 不需要 `tenant_id` 和 `client_secret`

## 参考文档

- `DEPLOY_LINUX.md` - Alibaba Cloud Linux 部署指南
- `DEPLOY_DEBIAN.md` - Debian 12 部署指南
