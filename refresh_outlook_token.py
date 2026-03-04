#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
from typing import Any, Dict

import httpx

DEFAULT_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All "
DEFAULT_SCOPE += "offline_access"
DEFAULT_TIMEOUT = 30.0


def default_config_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    raise ValueError("配置文件顶层必须是对象")


def save_config(path: str, cfg: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def short_value(value: str, keep: int = 10) -> str:
    if len(value) <= keep * 2:
        return value
    return f"{value[:keep]}...{value[-keep:]}"


def build_form(
    cfg: Dict[str, Any],
    scope: str,
) -> tuple[str, str, Dict[str, str]]:
    tenant_id = str(cfg.get("imap_oauth2_tenant_id") or "").strip()
    client_id = str(cfg.get("imap_oauth2_client_id") or "").strip()
    refresh_token = str(cfg.get("imap_oauth2_refresh_token") or "").strip()

    missing = []
    if not tenant_id:
        missing.append("imap_oauth2_tenant_id")
    if not client_id:
        missing.append("imap_oauth2_client_id")
    if not refresh_token:
        missing.append("imap_oauth2_refresh_token")
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"缺少必要配置: {joined}")

    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": scope,
    }
    client_secret = str(cfg.get("imap_oauth2_client_secret") or "").strip()
    if client_secret:
        data["client_secret"] = client_secret
    return tenant_id, client_id, data


def parse_error(resp: httpx.Response) -> str:
    text = resp.text.strip()
    try:
        data = resp.json()
    except Exception:
        return text[:800]
    if not isinstance(data, dict):
        return text[:800]

    err = str(data.get("error") or "").strip()
    desc = str(data.get("error_description") or "").strip()
    if err and desc:
        return f"{err}: {desc}"
    if err:
        return err
    if desc:
        return desc
    return text[:800]


def refresh_once(
    cfg: Dict[str, Any],
    scope: str,
    timeout: float,
) -> Dict[str, Any]:
    tenant_id, client_id, data = build_form(cfg, scope)
    token_url = "https://login.microsoftonline.com/"
    token_url += f"{tenant_id}/oauth2/v2.0/token"

    print(f"[*] Token endpoint: {token_url}")
    print(f"[*] Client ID: {short_value(client_id, keep=8)}")
    print("[*] Sending refresh_token request as form data...")

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(token_url, data=data)

    print(f"[*] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        detail = parse_error(resp)
        raise RuntimeError(f"刷新失败: {detail}")

    try:
        token_data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"返回内容不是 JSON: {exc}") from exc

    if not isinstance(token_data, dict):
        raise RuntimeError("返回内容不是对象 JSON")

    access_token = str(token_data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("刷新成功但未返回 access_token")

    expires_in = int(token_data.get("expires_in") or 3600)
    cfg["imap_oauth2_token"] = access_token
    cfg["imap_oauth2_token_expires_at"] = int(time.time()) + expires_in

    new_refresh = str(token_data.get("refresh_token") or "").strip()
    if new_refresh:
        cfg["imap_oauth2_refresh_token"] = new_refresh

    return token_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="单独测试 Outlook OAuth2 refresh_token 刷新"
    )
    parser.add_argument(
        "--config",
        default=default_config_path(),
        help="配置文件路径，默认仓库根目录 config.json",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="刷新时使用的 scope",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP 超时秒数",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只请求不落盘更新 config.json",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        token_data = refresh_once(cfg, args.scope, args.timeout)
        if not args.dry_run:
            save_config(args.config, cfg)

        access_token = str(token_data.get("access_token") or "")
        refresh_token = str(token_data.get("refresh_token") or "")

        print("[OK] Token 刷新成功")
        print(f"[OK] access_token: {short_value(access_token, keep=12)}")
        if refresh_token:
            print(f"[OK] refresh_token: {short_value(refresh_token, keep=12)}")
        if args.dry_run:
            print("[!] dry-run 模式，未写回 config.json")
            return 0

        print(f"[OK] 已写回配置: {args.config}")
        return 0
    except Exception as exc:
        print(f"[Error] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
