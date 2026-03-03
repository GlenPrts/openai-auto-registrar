#!/usr/bin/env python3
"""
Outlook IMAP OAuth2 配置测试脚本

用法:
    python test_outlook_oauth2.py

功能:
    1. 读取 config.json 配置
    2. 检查 OAuth2 配置项是否完整
    3. 检查 Token 是否即将过期
    4. 自动刷新过期/即将过期的 Token
    5. 连接 IMAP 服务器验证
    6. 获取收件箱统计信息
    7. 尝试获取最近邮件
"""

import json
import os
import sys
import time
from datetime import datetime

import httpx
import imaplib
from imap_tools import MailBox

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")


def load_config():
    """加载配置文件。"""
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 配置文件不存在: {CONFIG_PATH}")
        print("💡 请先复制 config.template.json 为 config.json 并填写配置")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    """保存配置到文件。"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print("💾 配置已更新到 config.json")


def print_section(title):
    """打印带分隔线的标题。"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def check_config(cfg):
    """检查配置是否完整。"""
    print_section("配置检查")

    required_fields = [
        "imap_host",
        "imap_port",
        "imap_user",
        "imap_auth_mode",
    ]

    oauth2_fields = [
        "imap_oauth2_token",
        "imap_oauth2_refresh_token",
        "imap_oauth2_client_id",
        "imap_oauth2_tenant_id",
    ]

    errors = []
    warnings = []

    for field in required_fields:
        if not cfg.get(field):
            errors.append(f"  ❌ 缺少必要配置: {field}")

    if cfg.get("imap_auth_mode") == "oauth2":
        print("📋 认证模式: OAuth2")
        for field in oauth2_fields:
            value = cfg.get(field, "")
            if not value:
                errors.append(f"  ❌ 缺少 OAuth2 配置: {field}")
            else:
                # 显示前20个字符
                display_value = value[:20] + "..." if len(value) > 20 else value
                print(f"  ✅ {field}: {display_value}")
    else:
        print(f"📋 认证模式: {cfg.get('imap_auth_mode', '未设置')} (非 OAuth2)")
        warnings.append("  ⚠️ 当前不是 OAuth2 模式，跳过 OAuth2 测试")

    if errors:
        print("\n❌ 配置错误:")
        for error in errors:
            print(error)
        return False

    if warnings:
        print("\n⚠️ 警告:")
        for warning in warnings:
            print(warning)

    print("\n✅ 配置检查通过")
    return True


def check_token_expiry(cfg):
    """检查 Token 过期时间。"""
    print_section("Token 有效期检查")

    expires_at = cfg.get("imap_oauth2_token_expires_at", 0)
    if not expires_at:
        print("⚠️ 未设置过期时间 (imap_oauth2_token_expires_at)")
        print("💡 脚本将尝试刷新 Token")
        return False

    current_time = int(time.time())
    expires_datetime = datetime.fromtimestamp(expires_at)
    current_datetime = datetime.fromtimestamp(current_time)

    print(f"  当前时间: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  过期时间: {expires_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    time_left = expires_at - current_time

    if time_left <= 0:
        print(f"  ❌ Token 已过期 {abs(time_left) // 60} 分钟")
        return False
    elif time_left < 300:
        print(f"  ⚠️ Token 即将过期，剩余 {time_left // 60} 分钟")
        return False
    else:
        hours = time_left // 3600
        minutes = (time_left % 3600) // 60
        print(f"  ✅ Token 有效，剩余 {hours}小时{minutes}分钟")
        return True


def refresh_outlook_token(cfg):
    """刷新 Outlook OAuth2 Token。"""
    print_section("刷新 Outlook Token")

    tenant_id = cfg.get("imap_oauth2_tenant_id", "")
    client_id = cfg.get("imap_oauth2_client_id", "")
    client_secret = cfg.get("imap_oauth2_client_secret", "")
    refresh_token = cfg.get("imap_oauth2_refresh_token", "")

    if not all([tenant_id, client_id, refresh_token]):
        print("❌ 缺少刷新 Token 所需的配置")
        return False

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }

    print(f"  🔄 请求 URL: {token_url[:50]}...")
    print(f"  🔄 Client ID: {client_id[:20]}...")

    try:
        resp = httpx.post(token_url, data=data, timeout=30)
        print(f"  📡 HTTP 状态: {resp.status_code}")

        if resp.status_code != 200:
            print(f"❌ Token 刷新失败")
            print(f"   响应: {resp.text[:500]}")
            return False

        token_data = resp.json()

        # 更新配置
        cfg["imap_oauth2_token"] = token_data.get("access_token", "")
        new_refresh_token = token_data.get("refresh_token", "")
        if new_refresh_token:
            cfg["imap_oauth2_refresh_token"] = new_refresh_token
            print("  ✅ 获取到新的 Refresh Token")

        expires_in = token_data.get("expires_in", 3600)
        cfg["imap_oauth2_token_expires_at"] = int(time.time()) + expires_in

        save_config(cfg)

        print(f"✅ Token 刷新成功")
        print(f"   新的 Access Token: {cfg['imap_oauth2_token'][:30]}...")
        print(f"   有效期: {expires_in // 60} 分钟")

        return True

    except Exception as e:
        print(f"❌ Token 刷新异常: {e}")
        return False


def build_oauth2_string(user: str, access_token: str) -> str:
    """构建 XOAUTH2 认证字符串。"""
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01"


def test_imap_connection(cfg):
    """测试 IMAP 连接。"""
    print_section("IMAP 连接测试")

    host = cfg.get("imap_host", "")
    port = cfg.get("imap_port", 993)
    user = cfg.get("imap_user", "")
    access_token = cfg.get("imap_oauth2_token", "")

    print(f"  服务器: {host}:{port}")
    print(f"  用户名: {user}")
    print(f"  认证方式: OAuth2 (XOAUTH2)")

    try:
        print("\n  🔄 连接到 IMAP 服务器...")
        client = imaplib.IMAP4_SSL(host, port=port)
        print("  ✅ SSL 连接成功")

        print("  🔄 发送 OAuth2 认证...")
        auth_string = build_oauth2_string(user, access_token)
        client.authenticate("XOAUTH2", lambda _: auth_string.encode())
        print("  ✅ OAuth2 认证成功")

        print("  🔄 选择收件箱...")
        client.select("INBOX")
        print("  ✅ 收件箱选择成功")

        # 获取统计信息
        status, messages = client.search(None, "ALL")
        msg_count = len(messages[0].split())
        print(f"\n  📊 收件箱统计: {msg_count} 封邮件")

        # 获取最近几封邮件
        if msg_count > 0:
            print("\n  📧 最近 3 封邮件:")
            mailbox = MailBox(host, port=port)
            mailbox.client = client

            for i, msg in enumerate(mailbox.fetch(limit=3, reverse=True)):
                print(f"\n    [{i + 1}] 主题: {msg.subject[:50]}")
                print(f"        来自: {msg.from_}")
                print(f"        时间: {msg.date}")

        client.logout()
        print("\n✅ IMAP 连接测试通过")
        return True

    except imaplib.IMAP4.error as e:
        error_str = str(e)
        print(f"\n❌ IMAP 错误: {error_str}")

        if "AUTHENTICATE failed" in error_str:
            print("\n💡 可能的原因:")
            print("   1. Access Token 已过期或无效")
            print("   2. OAuth2 权限不足（需要 IMAP.AccessAsUser.All）")
            print("   3. Azure AD 应用未授权")
        elif "connection" in error_str.lower():
            print("\n💡 无法连接到服务器，请检查:")
            print("   1. 网络连接")
            print("   2. IMAP 服务器地址和端口")
            print("   3. 防火墙设置")

        return False

    except Exception as e:
        print(f"\n❌ 连接异常: {e}")
        return False


def main():
    print("\n" + "#" * 60)
    print("# Outlook IMAP OAuth2 配置测试工具")
    print("#" * 60)

    # 加载配置
    cfg = load_config()

    # 检查配置
    if not check_config(cfg):
        sys.exit(1)

    # 如果是 OAuth2 模式
    if cfg.get("imap_auth_mode") == "oauth2":
        # 检查 Token 是否过期
        if not check_token_expiry(cfg):
            # 尝试刷新
            if not refresh_outlook_token(cfg):
                print("\n❌ 无法获取有效 Token，测试终止")
                sys.exit(1)
            # 重新加载配置
            cfg = load_config()

        # 测试 IMAP 连接
        if test_imap_connection(cfg):
            print_section("测试结果")
            print("🎉 所有测试通过！配置正确。")
            print("\n您可以正常使用 main.py 进行自动注册了。")
            sys.exit(0)
        else:
            print_section("测试结果")
            print("❌ IMAP 连接失败")
            print("\n请检查:")
            print("  1. Azure AD 应用权限设置")
            print("  2. OAuth2 Token 是否有效")
            print("  3. 邮箱账户是否启用 IMAP")
            sys.exit(1)
    else:
        print_section("测试结果")
        print("⚠️ 当前不是 OAuth2 模式，跳过后续测试")
        print(f"当前模式: {cfg.get('imap_auth_mode')}")


if __name__ == "__main__":
    main()
