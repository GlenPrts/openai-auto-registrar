import json
import os
import re
import sys
import time
import uuid
import math
import random
import string
import secrets
import hashlib
import base64
import threading
import argparse
import imaplib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, quote
from dataclasses import dataclass
from typing import Any, Dict, Optional
import urllib.parse
import urllib.request
import urllib.error

from curl_cffi import requests

# Token 保存目录
TOKEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens")

# IMAP 支持
IMAP_TOOLS_AVAILABLE = False
MailBox = None

try:
    from imap_tools import MailBox as _MailBox

    MailBox = _MailBox
    IMAP_TOOLS_AVAILABLE = True
except ImportError:
    pass

# ==========================================
# 邮箱配置管理
# ==========================================

# IMAP 配置文件路径
IMAP_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json"
)


def load_imap_config() -> Optional[Dict[str, Any]]:
    """加载 IMAP 配置。"""
    if not os.path.exists(IMAP_CONFIG_PATH):
        print(f"[Warning] IMAP 配置文件不存在: {IMAP_CONFIG_PATH}")
        return None

    try:
        with open(IMAP_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"[Error] 读取 IMAP 配置失败: {e}")
        return None


def save_imap_config(config: Dict[str, Any]) -> bool:
    try:
        with open(IMAP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Warning] 保存 IMAP 配置失败: {e}")
        return False


def generate_imap_email(config: Dict[str, Any]) -> str:
    """基于配置生成随机 IMAP 邮箱地址。"""
    domain = config.get("domain", "example.com")
    prefix = config.get("email_prefix", "auto")
    random_suffix = uuid.uuid4().hex
    return f"{prefix}{random_suffix}@{domain}"


# ==========================================
# Mail.tm 临时邮箱 API
# ==========================================

MAILTM_BASE = "https://api.mail.tm"


def _mailtm_headers(*, token: str = "", use_json: bool = False) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if use_json:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mailtm_domains(proxies: Any = None) -> list[str]:
    resp = requests.get(
        f"{MAILTM_BASE}/domains",
        headers=_mailtm_headers(),
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Mail.tm 域名失败，状态码: {resp.status_code}")

    data = resp.json()
    domains = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("hydra:member") or data.get("items") or []
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        is_active = item.get("isActive", True)
        is_private = item.get("isPrivate", False)
        if domain and is_active and not is_private:
            domains.append(domain)

    return domains


def get_email_and_token(proxies: Any = None) -> tuple[str, str]:
    """创建 Mail.tm 邮箱并获取 Bearer Token"""
    try:
        domains = _mailtm_domains(proxies)
        if not domains:
            print("[Error] Mail.tm 没有可用域名")
            return "", ""
        domain = random.choice(domains)

        for _ in range(5):
            local = f"oc{secrets.token_hex(5)}"
            email = f"{local}@{domain}"
            password = secrets.token_urlsafe(18)

            create_resp = requests.post(
                f"{MAILTM_BASE}/accounts",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )

            if create_resp.status_code not in (200, 201):
                continue

            token_resp = requests.post(
                f"{MAILTM_BASE}/token",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )

            if token_resp.status_code == 200:
                token = str(token_resp.json().get("token") or "").strip()
                if token:
                    return email, token

        print("[Error] Mail.tm 邮箱创建成功但获取 Token 失败")
        return "", ""
    except Exception as e:
        print(f"[Error] 请求 Mail.tm API 出错: {e}")
        return "", ""


# ==========================================
# IMAP 邮箱验证码获取
# ==========================================


def build_oauth2_string(user: str, access_token: str) -> str:
    """构建 XOAUTH2 认证字符串。"""
    auth_string = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    return auth_string


def refresh_outlook_token(config: Dict[str, Any]) -> Optional[str]:
    """刷新 Outlook/Microsoft OAuth2 Token。"""
    refresh_token = config.get("imap_oauth2_refresh_token", "")
    client_id = config.get("imap_oauth2_client_id", "")
    tenant_id = config.get("imap_oauth2_tenant_id", "")
    client_secret = config.get("imap_oauth2_client_secret", "")

    if not refresh_token or not client_id or not tenant_id:
        return None

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        resp = requests.post(token_url, data=data, timeout=30)
        if resp.status_code != 200:
            detail = ""
            try:
                err_data = resp.json()
                err = str(err_data.get("error") or "").strip()
                desc = str(err_data.get("error_description") or "").strip()
                if err:
                    detail = err
                if desc:
                    detail = f"{detail}: {desc}" if detail else desc
            except Exception:
                detail = str(resp.text or "")[:240]

            print(f"[Error] Token 刷新失败: {resp.status_code}")
            if detail:
                print(f"[Error] Token 刷新详情: {detail}")
            return None

        token_data = resp.json()
        access_token = str(token_data.get("access_token") or "").strip()
        if not access_token:
            print("[Error] 刷新成功但未返回 access_token")
            return None

        config["imap_oauth2_token"] = access_token
        expires_in = int(token_data.get("expires_in") or 3600)
        config["imap_oauth2_token_expires_at"] = int(time.time()) + expires_in

        new_refresh_token = str(token_data.get("refresh_token") or "").strip()
        if new_refresh_token:
            config["imap_oauth2_refresh_token"] = new_refresh_token

        save_imap_config(config)
        return access_token
    except Exception as e:
        print(f"[Error] Token 刷新异常: {e}")
        return None


def get_imap_oauth2_token(config: Dict[str, Any]) -> Optional[str]:
    """获取有效的 OAuth2 Token（如有必要则刷新）。"""
    auth_mode = config.get("imap_auth_mode", "password")
    if auth_mode != "oauth2":
        return None

    token = config.get("imap_oauth2_token", "")
    expires_at = config.get("imap_oauth2_token_expires_at", 0)

    # 检查是否即将过期（5分钟缓冲）
    current_time = int(time.time())
    if expires_at > current_time + 300:
        return token

    # 需要刷新
    print("[*] OAuth2 Token 即将过期，尝试刷新...")
    new_token = refresh_outlook_token(config)
    return new_token if new_token else token


def create_imap_mailbox(config: Dict[str, Any]):
    """根据配置创建 IMAP 连接。"""
    if not IMAP_TOOLS_AVAILABLE or MailBox is None:
        raise RuntimeError("未安装 imap-tools，请运行: pip install imap-tools")

    host = config.get("imap_host", "")
    port = config.get("imap_port", 993)
    user = config.get("imap_user", "")
    password = config.get("imap_pass", "")
    auth_mode = config.get("imap_auth_mode", "password")

    if auth_mode == "oauth2":
        access_token = get_imap_oauth2_token(config)
        if not access_token:
            raise RuntimeError("OAuth2 Token 无效")

        client = imaplib.IMAP4_SSL(host, port=port)
        auth_string = build_oauth2_string(user, access_token)
        client.authenticate("XOAUTH2", lambda _: auth_string.encode())
        client.select("INBOX")
        mailbox = MailBox(host, port=port)
        mailbox.client = client
        return mailbox

    return MailBox(host, port=port).login(user, password)


def get_code_from_imap(config: Dict[str, Any], email: str, proxies: Any = None) -> str:
    """通过 IMAP 获取 OpenAI 验证码。"""
    if not IMAP_TOOLS_AVAILABLE:
        print("[Error] 未安装 imap-tools，无法使用 IMAP 邮箱")
        return ""

    print(f"[*] 正在等待 IMAP 邮箱 {email} 的验证码...", end="", flush=True)

    email_lower = email.lower()
    start_time = time.time()
    timeout = 120  # 2分钟超时

    try:
        mailbox = create_imap_mailbox(config)
        seen_uids = set()

        while time.time() - start_time < timeout:
            print(".", end="", flush=True)

            # 保持连接活跃
            try:
                mailbox.client.noop()
            except Exception:
                pass

            for msg in mailbox.fetch(limit=10, reverse=True):
                if msg.uid in seen_uids:
                    continue
                seen_uids.add(msg.uid)

                # 检查邮件时间（只处理最近10分钟的邮件）
                if msg.date and (time.time() - msg.date.timestamp()) > 600:
                    continue

                # 检查发件人
                if msg.from_ and "openai" not in msg.from_.lower():
                    continue

                # 检查收件人匹配
                recipient_matched = any(email_lower in t.lower() for t in msg.to)

                # 检查转发头
                if not recipient_matched:
                    for header_name in (
                        "delivered-to",
                        "x-original-to",
                        "x-forwarded-to",
                    ):
                        vals = msg.headers.get(header_name) or []
                        if any(email_lower in v.lower() for v in vals):
                            recipient_matched = True
                            break

                # 检查正文
                if not recipient_matched:
                    body_check = msg.text or msg.html or ""
                    if email_lower in body_check.lower():
                        recipient_matched = True

                if not recipient_matched:
                    continue

                # 查找验证码
                body = msg.text or msg.html or ""
                match = re.search(r"\b(\d{6})\b", body)
                if match:
                    code = match.group(1)
                    print(f" 抓到啦! 验证码: {code}")
                    # 删除邮件
                    uid = msg.uid
                    if uid:
                        try:
                            mailbox.delete(uid)
                            mailbox.client.expunge()
                        except Exception as e:
                            print(f"[Warning] 删除验证码邮件失败: {e}")
                    return code

            time.sleep(3)

        print(" 超时，未收到验证码")
        return ""

    except Exception as e:
        print(f"\n[Error] IMAP 获取验证码失败: {e}")
        return ""


def get_email_and_token_imap(config: Dict[str, Any]) -> tuple[str, str]:
    """使用 IMAP 配置生成邮箱（Token 是配置本身）。"""
    email = generate_imap_email(config)
    # 返回邮箱和配置标识（用作 token）
    return email, "imap_config"


def get_oai_code(token: str, email: str, proxies: Any = None) -> str:
    """使用 Mail.tm Token 轮询获取 OpenAI 验证码"""
    url_list = f"{MAILTM_BASE}/messages"
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[str] = set()

    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                url_list,
                headers=_mailtm_headers(token=token),
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []
            else:
                messages = []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                read_resp = requests.get(
                    f"{MAILTM_BASE}/messages/{msg_id}",
                    headers=_mailtm_headers(token=token),
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if read_resp.status_code != 200:
                    continue

                mail_data = read_resp.json()
                sender = str(
                    ((mail_data.get("from") or {}).get("address") or "")
                ).lower()
                subject = str(mail_data.get("subject") or "")
                intro = str(mail_data.get("intro") or "")
                text = str(mail_data.get("text") or "")
                html = mail_data.get("html") or ""
                if isinstance(html, list):
                    html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                m = re.search(regex, content)
                if m:
                    print(" 抓到啦! 验证码:", m.group(1))
                    return m.group(1)
        except Exception:
            pass

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


# ==========================================
# OAuth 授权与辅助函数
# ==========================================

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

DEFAULT_REDIRECT_URI = f"http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, str]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)

    if not error and error_description:
        error, error_description = error_description, ""

    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _decode_jwt_segment(seg: str) -> Dict[str, Any]:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(
                    f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(
            f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}"
        ) from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(
    *, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> str:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())

    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": cb["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
    )
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


# ==========================================
# 核心注册逻辑
# ==========================================


def run(proxy: Optional[str], email_mode: str = "mailtm") -> Optional[str]:
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    s = requests.Session(proxies=proxies, impersonate="chrome")

    try:
        trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
        trace = trace.text
        loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_re.group(1) if loc_re else None
        print(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN" or loc == "HK":
            raise RuntimeError("检查代理哦w - 所在地不支持")
    except Exception as e:
        print(f"[Error] 网络连接检查失败: {e}")
        return None

    # 根据邮箱模式获取邮箱和验证码获取方式
    imap_config = None
    if email_mode == "imap":
        imap_config = load_imap_config()
        if not imap_config:
            print("[Error] 无法加载 IMAP 配置，回退到 Mail.tm")
            email_mode = "mailtm"

    dev_token: str = ""
    if email_mode == "imap":
        if imap_config is None:
            print("[Error] IMAP 配置未加载")
            return None
        email, dev_token = get_email_and_token_imap(imap_config)
        print(f"[*] 使用 IMAP 邮箱: {email}")
    else:
        email, dev_token = get_email_and_token(proxies)
        if not email or not dev_token:
            return None
        print(f"[*] 成功获取 Mail.tm 邮箱与授权: {email}")

    oauth = generate_oauth_url()
    url = oauth.auth_url

    try:
        resp = s.get(url, timeout=15)
        did = s.cookies.get("oai-did")
        print(f"[*] Device ID: {did}")

        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )

        if sen_resp.status_code != 200:
            print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
        )
        print(f"[*] 提交注册表单状态: {signup_resp.status_code}")

        otp_resp = s.post(
            "https://auth.openai.com/api/accounts/passwordless/send-otp",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        print(f"[*] 验证码发送状态: {otp_resp.status_code}")

        # 根据邮箱模式获取验证码
        if email_mode == "imap" and imap_config is not None:
            code = get_code_from_imap(imap_config, email, proxies)
        else:
            code = get_oai_code(dev_token, email, proxies)
        if not code:
            return None

        code_body = f'{{"code":"{code}"}}'
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
        )
        print(f"[*] 验证码校验状态: {code_resp.status_code}")

        create_account_body = '{"name":"Neo","birthdate":"2000-02-20"}'
        create_account_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
        )
        create_account_status = create_account_resp.status_code
        print(f"[*] 账户创建状态: {create_account_status}")

        if create_account_status != 200:
            print(create_account_resp.text)
            return None

        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            print("[Error] 未能获取到授权 Cookie")
            return None

        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[Error] 授权 Cookie 里没有 workspace 信息")
            return None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        if not workspace_id:
            print("[Error] 无法解析 workspace_id")
            return None

        select_body = f'{{"workspace_id":"{workspace_id}"}}'
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
        )

        if select_resp.status_code != 200:
            print(f"[Error] 选择 workspace 失败，状态码: {select_resp.status_code}")
            print(select_resp.text)
            return None

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[Error] workspace/select 响应里缺少 continue_url")
            return None

        current_url = continue_url
        for _ in range(6):
            final_resp = s.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                return submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                )
            current_url = next_url

        print("[Error] 未能在重定向链中捕获到最终 Callback URL")
        return None

    except Exception as e:
        print(f"[Error] 运行时发生错误: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI 自动注册脚本")
    parser.add_argument(
        "--proxy", default=None, help="代理地址，如 http://127.0.0.1:7890"
    )
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--sleep-min", type=int, default=5, help="循环模式最短等待秒数")
    parser.add_argument(
        "--sleep-max", type=int, default=30, help="循环模式最长等待秒数"
    )
    parser.add_argument(
        "--email-mode",
        choices=["mailtm", "imap"],
        default="mailtm",
        help="邮箱模式: mailtm (默认, 使用 Mail.tm 临时邮箱) 或 imap (使用 @openai-auto-register 的 IMAP 配置)",
    )
    args = parser.parse_args()

    sleep_min = max(1, args.sleep_min)
    sleep_max = max(sleep_min, args.sleep_max)

    count = 0
    print("[Info] Yasal's Seamless OpenAI Auto-Registrar Started for ZJH")
    print(f"[*] 邮箱模式: {args.email_mode}")

    while True:
        count += 1
        print(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> 开始第 {count} 次注册流程 <<<"
        )

        try:
            token_json = run(args.proxy, args.email_mode)

            if token_json:
                try:
                    t_data = json.loads(token_json)
                    fname_email = t_data.get("email", "unknown").replace("@", "_")
                except Exception:
                    fname_email = "unknown"

                os.makedirs(TOKEN_DIR, exist_ok=True)
                file_name = f"token_{fname_email}_{int(time.time())}.json"
                file_path = os.path.join(TOKEN_DIR, file_name)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(token_json)

                print(f"[*] 成功! Token 已保存至: {file_path}")
            else:
                print("[-] 本次注册失败。")

        except Exception as e:
            print(f"[Error] 发生未捕获异常: {e}")

        if args.once:
            break

        wait_time = random.randint(sleep_min, sleep_max)
        print(f"[*] 休息 {wait_time} 秒...")
        time.sleep(wait_time)


if __name__ == "__main__":
    main()
