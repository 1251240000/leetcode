#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

DOMAIN = "leetcode.cn"
TARGET_URL = "https://" + DOMAIN + "/problemset/all/"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
USER_DATA_DIR = os.path.expanduser("~/.leetcode_profile")

def save_to_env(session: str, csrf: str):
    """保存凭据到 .env 文件"""
    content = f"""# 自动生成的 LeetCode 凭据 ({time.strftime('%Y-%m-%d %H:%M:%S')})
LEETCODE_SESSION="{session}"
CSRF_TOKEN="{csrf}"
DRY_RUN=false
"""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
    logger.info(f"✅ 凭据已即时保存至本地: {ENV_FILE}")

def extract_tokens():
    logger.info("正在调起 Chrome 浏览器...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TARGET_URL)
        
        logger.info("正在等待登录态（检测到瞬间将直接返回）...")

        session_token = None
        csrf_token = None

        # 0.5 秒高频扫描 Cookie
        for _ in range(240):
            for item in context.cookies():
                if item.get("name") == "LEETCODE_SESSION":
                    session_token = item.get("value")
                elif item.get("name") == "csrftoken":
                    csrf_token = item.get("value")

            # 一旦拿到两个核心 Token，立即落盘并退出
            if session_token and csrf_token:
                logger.info("🎉 登录成功，瞬间捕获凭证！")
                print("-" * 55)
                print(f"LEETCODE_SESSION: {session_token[:12]}...{session_token[-8:]}")
                print(f"CSRF_TOKEN:       {csrf_token}")
                print("-" * 55)
                save_to_env(session_token, csrf_token)
                
                # 尝试关闭页面窗口
                try:
                    page.close()
                except Exception:
                    pass
                
                # 强行瞬间终止 Python 进程，不再等待 Chrome 后台垃圾回收与同步
                os._exit(0)
            
            time.sleep(0.5)

        logger.error("❌ 超时未检测到登录凭证，请重试。")
        os._exit(1)

if __name__ == "__main__":
    extract_tokens()
