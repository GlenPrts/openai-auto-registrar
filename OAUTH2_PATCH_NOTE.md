# OAuth2 刷新补丁说明（2026-03-04）

## 目标

修复 `[*] OAuth2 Token 即将过期...` 后返回 400 的问题，
并提供独立排查脚本。

## 根因

`singup.py` 中刷新 token 请求使用了 JSON body：

`requests.post(token_url, json=data, ...)`

Microsoft v2 token endpoint 需要 form body
（`application/x-www-form-urlencoded`）。
因此会触发 400。

## 变更明细

### 1) `singup.py`

- 新增 `save_imap_config(config)`，用于刷新成功后落盘。
- `refresh_outlook_token` 调整：
  - `json=data` 改为 `data=data`
  - `client_secret` 改为有值才发送
  - 失败时解析并输出 `error` / `error_description`
  - 成功时回写以下字段：
    - `imap_oauth2_token`
    - `imap_oauth2_refresh_token`（若服务端返回）
    - `imap_oauth2_token_expires_at`

> 注：同文件还修复了非 OAuth2 的 `msg.uid` 判空问题，
> 避免 `mailbox.delete(None)` 风险。

### 2) `test_outlook_oauth2.py`

- 刷新请求中 `client_secret` 改为可选字段。
- 失败输出改为优先展示 `error` / `error_description`。

### 3) `refresh_outlook_token.py`（新增）

- 独立 refresh_token 测试脚本，支持：
  - `--config`
  - `--scope`
  - `--timeout`
  - `--dry-run`
- 成功时可写回 `config.json`；失败时输出可定位错误详情。

## 验证结果

- `uv run python -m py_compile singup.py test_outlook_oauth2.py \
  refresh_outlook_token.py` 通过。
- `uv run python refresh_outlook_token.py --config config.json`
  返回 HTTP 200。
- `uv run python test_outlook_oauth2.py`
  通过 OAuth2 刷新与 IMAP 认证。

## 使用方式

- 仅测试不落盘：
  - `uv run python refresh_outlook_token.py \
    --config config.json --dry-run`
- 刷新并写回：
  - `uv run python refresh_outlook_token.py --config config.json`

## 仍可能出现 400 的常见原因

- `invalid_grant`：refresh_token 过期、撤销，或与 app 不匹配
- `invalid_client`：client_secret 错误、过期，或本应必填却缺失
- `invalid_request`：tenant、scope 或参数缺失不匹配

## 回滚说明

- 回滚 OAuth2 补丁：
  - `git checkout -- singup.py test_outlook_oauth2.py`
  - `git clean -f refresh_outlook_token.py`
