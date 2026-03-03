#!/usr/bin/env python3
"""
Outlook OAuth2 Token 自动获取脚本

功能:
    1. 启动本地 HTTP 服务器接收 OAuth2 回调
    2. 自动打开浏览器让用户登录授权
    3. 自动提取 authorization code
    4. 自动换取 access_token 和 refresh_token
    5. 自动更新 config.json

用法:
    python get_outlook_token.py

配置要求:
    config.json 中需预先填写:
    - imap_oauth2_client_id
    - imap_oauth2_tenant_id
"""

import json
import os
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

import httpx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CALLBACK_PORT = 1456
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}"

auth_code = None
server_running = True


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print("💾 配置已保存到 config.json")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, server_running

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if "code" in query:
            auth_code = query["code"][0]
            print(f"\n✅ 获取到 Authorization Code: {auth_code[:20]}...")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Authorization Success</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .container {
            text-align: center;
            padding: 40px;
        }
        h1 {
            font-size: 3rem;
            margin-bottom: 20px;
        }
        p {
            font-size: 1.2rem;
            opacity: 0.9;
        }
        .code {
            background: rgba(255,255,255,0.2);
            padding: 10px 20px;
            border-radius: 8px;
            font-family: monospace;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>[OK] Authorization Success</h1>
        <p>Exchanging token, please wait...</p>
        <div class="code">Code received</div>
    </div>
</body>
</html>"""
            self.wfile.write(html_content.encode("utf-8"))
            server_running = False

        elif "error" in query:
            error = query["error"][0]
            print(f"\n❌ 授权失败: {error}")

            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Authorization Failed</title></head>
<body style="font-family: sans-serif; text-align: center; padding-top: 100px;">
    <h1 style="color: #e74c3c;">[X] Authorization Failed</h1>
    <p>Error: {error}</p>
    <p>Please close the window and try again</p>
</body>
</html>"""
            self.wfile.write(html_content.encode("utf-8"))
            server_running = False

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_callback_server():
    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), OAuthCallbackHandler)
    print(f"🌐 回调服务器已启动: {REDIRECT_URI}")

    while server_running:
        server.handle_request()

    server.server_close()
    print("🔒 回调服务器已关闭")


def build_auth_url(client_id, tenant_id):
    scope = quote("https://outlook.office.com/IMAP.AccessAsUser.All offline_access")
    return (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={quote(REDIRECT_URI)}&"
        f"scope={scope}&"
        f"prompt=consent"
    )


def exchange_code_for_token(code, cfg):
    tenant_id = cfg.get("imap_oauth2_tenant_id", "")
    client_id = cfg.get("imap_oauth2_client_id", "")
    client_secret = cfg.get("imap_oauth2_client_secret", "")

    token_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    )
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }

    print("\n🔄 正在换取 Token...")
    print(f"   URL: {token_url}")
    print(f"   Client ID: {client_id[:20]}...")

    try:
        resp = httpx.post(token_url, data=data, timeout=30)
        print(f"   HTTP 状态: {resp.status_code}")

        if resp.status_code != 200:
            print(f"❌ Token 换取失败")
            print(f"   响应: {resp.text[:500]}")
            return None

        token_data = resp.json()
        return token_data

    except Exception as e:
        print(f"❌ 请求异常: {e}")
        return None


def update_config(cfg, token_data):
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        print("❌ 响应中没有 access_token")
        return False

    if not refresh_token:
        print("⚠️ 警告: 响应中没有 refresh_token")
        print("   可能 scope 中没有包含 offline_access")

    cfg["imap_oauth2_token"] = access_token
    cfg["imap_oauth2_refresh_token"] = refresh_token
    cfg["imap_oauth2_token_expires_at"] = int(time.time()) + expires_in
    cfg["imap_auth_mode"] = "oauth2"
    cfg["imap_host"] = "outlook.office365.com"
    cfg["imap_port"] = 993

    if not cfg.get("imap_pass"):
        cfg["imap_pass"] = ""

    save_config(cfg)

    print("\n" + "=" * 60)
    print("🎉 Token 获取成功!")
    print("=" * 60)
    print(f"📧 邮箱: {cfg.get('imap_user', '未设置')}")
    print(f"🔑 Access Token: {access_token[:40]}...")
    print(
        f"🔄 Refresh Token: {refresh_token[:40]}..."
        if refresh_token
        else "🔄 Refresh Token: 无"
    )
    print(f"⏰ 有效期: {expires_in // 60} 分钟")
    print(
        f"📅 过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cfg['imap_oauth2_token_expires_at']))}"
    )
    print("=" * 60)

    return True


def main():
    print("\n" + "#" * 60)
    print("# Outlook OAuth2 Token 自动获取工具")
    print("#" * 60)

    cfg = load_config()

    client_id = cfg.get("imap_oauth2_client_id", "")
    tenant_id = cfg.get("imap_oauth2_tenant_id", "")

    if not client_id or not tenant_id:
        print("\n❌ 缺少必要配置")
        print("请在 config.json 中填写:")
        print("  - imap_oauth2_client_id")
        print("  - imap_oauth2_tenant_id")
        print("\n获取方法:")
        print("  1. 访问 https://portal.azure.com/")
        print("  2. 进入 Microsoft Entra ID → 应用注册")
        print("  3. 创建新应用并记录 Client ID 和 Tenant ID")
        sys.exit(1)

    print(f"\n📋 配置信息:")
    print(f"   Client ID: {client_id}")
    print(f"   Tenant ID: {tenant_id}")
    print(f"   Redirect URI: {REDIRECT_URI}")

    auth_url = build_auth_url(client_id, tenant_id)

    print("\n🔧 启动回调服务器...")
    import threading

    server_thread = threading.Thread(target=start_callback_server)
    server_thread.daemon = True
    server_thread.start()

    time.sleep(0.5)

    print("\n🌐 正在打开浏览器进行授权...")
    print("   如果没有自动打开，请手动访问以下链接:")
    print(f"   {auth_url}\n")

    webbrowser.open(auth_url)

    print("⏳ 等待授权完成...")
    server_thread.join(timeout=120)

    global auth_code
    if not auth_code:
        print("\n❌ 未获取到 Authorization Code")
        print("可能原因:")
        print("  1. 浏览器未打开或授权未完成")
        print("  2. 用户取消了授权")
        print("  3. 超时（120秒）")
        sys.exit(1)

    token_data = exchange_code_for_token(auth_code, cfg)
    if not token_data:
        sys.exit(1)

    if update_config(cfg, token_data):
        print("\n✅ 配置已自动更新到 config.json")
        print("\n接下来可以:")
        print("  1. 运行 python test_outlook_oauth2.py 测试配置")
        print("  2. 运行 python main.py 开始自动注册")
    else:
        print("\n❌ 更新配置失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
