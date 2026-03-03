import json
import os
import threading
import time
import glob
from fastapi import FastAPI, BackgroundTasks, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Optional
import singup
import zipfile
import io

TOKEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens")

app = FastAPI()

# Setup templates and state
if not os.path.exists("templates"):
    os.makedirs("templates")

templates = Jinja2Templates(directory="templates")
process_state = {
    "is_running": False,
    "count": 0,
    "success_count": 0,
    "fail_count": 0,
    "logs": [],
    "proxy": "",
    "email_mode": "mailtm",
    "stop_event": threading.Event(),
}


def add_log(message):
    timestamp = time.strftime("%H:%M:%S")
    msg = f"[{timestamp}] {message}"
    process_state["logs"].insert(0, msg)
    # Keep only the last 50 logs
    process_state["logs"] = process_state["logs"][:50]
    print(msg)


def registration_worker(proxy: Optional[str], email_mode: str = "mailtm"):
    process_state["is_running"] = True
    process_state["stop_event"].clear()

    mode_str = "IMAP" if email_mode == "imap" else "Mail.tm"
    add_log(f"[INFO] 注册服务已启动 (代理: {proxy or '无'}, 邮箱模式: {mode_str})")

    while not process_state["stop_event"].is_set():
        process_state["count"] += 1
        add_log(f"--- 第 {process_state['count']} 次注册开始 ---")

        try:
            # 运行注册逻辑
            token_json = singup.run(proxy, email_mode)

            if token_json:
                process_state["success_count"] += 1
                try:
                    t_data = json.loads(token_json)
                    email = t_data.get("email", "unknown").replace("@", "_")
                except:
                    email = "unknown"

                os.makedirs(TOKEN_DIR, exist_ok=True)
                file_name = f"token_{email}_{int(time.time())}.json"
                file_path = os.path.join(TOKEN_DIR, file_name)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(token_json)
                add_log(f"[SUCCESS] 注册成功! 文件已保存: {file_path}")
            else:
                process_state["fail_count"] += 1
                add_log("[FAIL] 注册失败。")

        except Exception as e:
            process_state["fail_count"] += 1
            add_log(f"[ERROR] 发生异常: {str(e)}")

        # 随机等待
        import random

        wait_time = random.randint(5, 30)
        add_log(f"[INFO] 休息 {wait_time} 秒...")

        for _ in range(wait_time):
            if process_state["stop_event"].is_set():
                break
            time.sleep(1)

    process_state["is_running"] = False
    add_log("[INFO] 注册服务已停止")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def get_status():
    return {
        "is_running": process_state["is_running"],
        "email_mode": process_state["email_mode"],
        "stats": {
            "total": process_state["count"],
            "success": process_state["success_count"],
            "fail": process_state["fail_count"],
        },
        "logs": process_state["logs"],
    }


@app.post("/api/start")
async def start_process(
    background_tasks: BackgroundTasks,
    proxy: Optional[str] = None,
    email_mode: Optional[str] = "mailtm",
):
    if process_state["is_running"]:
        return {"status": "already_running"}

    if email_mode not in ["mailtm", "imap"]:
        email_mode = "mailtm"

    process_state["proxy"] = proxy
    process_state["email_mode"] = email_mode
    background_tasks.add_task(registration_worker, proxy, email_mode)
    return {"status": "started", "email_mode": email_mode}


@app.post("/api/stop")
async def stop_process():
    if not process_state["is_running"]:
        return {"status": "not_running"}

    process_state["stop_event"].set()
    return {"status": "stopping"}


@app.get("/api/files")
async def list_files():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    pattern = os.path.join(TOKEN_DIR, "token_*.json")
    files = glob.glob(pattern)
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    file_list = []
    for f in files:
        file_list.append(
            {
                "name": os.path.basename(f),
                "size": f"{os.path.getsize(f) / 1024:.2f} KB",
                "time": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(f))
                ),
            }
        )
    return file_list


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(TOKEN_DIR, filename)
    if (
        os.path.exists(file_path)
        and filename.startswith("token_")
        and filename.endswith(".json")
    ):
        return FileResponse(
            path=file_path, filename=filename, media_type="application/json"
        )
    return {"error": "File not found"}


@app.get("/api/download_all")
async def download_all():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    pattern = os.path.join(TOKEN_DIR, "token_*.json")
    files = glob.glob(pattern)
    if not files:
        return {"error": "No files to download"}

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for file_path in files:
            zip_file.write(file_path, os.path.basename(file_path))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=all_tokens.zip"},
    )


@app.post("/api/delete_all")
async def delete_all():
    os.makedirs(TOKEN_DIR, exist_ok=True)
    pattern = os.path.join(TOKEN_DIR, "token_*.json")
    files = glob.glob(pattern)
    count = 0
    for f in files:
        try:
            os.remove(f)
            count += 1
        except:
            pass
    return {"status": "success", "deleted_count": count}


if __name__ == "__main__":
    import uvicorn

    # 从环境变量获取端口，默认为 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
