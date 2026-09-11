#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import logging
import warnings
import requests
from typing import Optional, Tuple, Dict, Any

# 忽略 macOS LibreSSL 与 urllib3 告警
try:
    import urllib3
    warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 自动从同目录下的 .env 读取配置
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

DOMAIN = "leetcode.cn"
BASE_URL = "https://" + DOMAIN
GRAPHQL_URL = BASE_URL + "/graphql/"

LEETCODE_SESSION = os.getenv("LEETCODE_SESSION", "").strip()
CSRF_TOKEN = os.getenv("CSRF_TOKEN", "").strip()
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

class LeetCodeBot:
    def __init__(self, session_token: str, csrf_token: str):
        self.session_token = session_token
        self.csrf_token = csrf_token
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "x-csrftoken": self.csrf_token,
            "Referer": BASE_URL + "/problemset/all/",
            "Origin": BASE_URL,
        })
        if self.session_token:
            self.http.cookies.set("LEETCODE_SESSION", self.session_token, domain="." + DOMAIN)
        if self.csrf_token:
            self.http.cookies.set("csrftoken", self.csrf_token, domain="." + DOMAIN)

    def get_daily_question(self) -> Dict[str, Any]:
        """获取每日一题信息"""
        query = """
        query questionOfToday {
            todayRecord {
                date
                userStatus
                question {
                    questionId
                    questionFrontendId
                    titleSlug
                    title
                    translatedTitle
                }
            }
        }
        """
        resp = self.http.post(
            GRAPHQL_URL,
            json={"operationName": "questionOfToday", "query": query},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        
        record = data.get("data", {}).get("todayRecord", [])[0]
        return {
            "date": record.get("date"),
            "user_status": record.get("userStatus"),  # FINISH 表示已打卡
            "question_id": record["question"]["questionId"],
            "frontend_id": record["question"]["questionFrontendId"],
            "title_slug": record["question"]["titleSlug"],
            "title": record["question"]["translatedTitle"] or record["question"]["title"],
        }

    def fetch_solution_candidates(self, title_slug: str, limit: int = 5) -> list:
        """获取高赞题解并提取 Python3 代码"""
        list_query = """
        query questionSolutionArticles($questionSlug: String!, $first: Int, $orderBy: SolutionArticleOrderBy) {
            questionSolutionArticles(questionSlug: $questionSlug, first: $first, orderBy: $orderBy) {
                edges {
                    node {
                        title
                        slug
                    }
                }
            }
        }
        """
        payload = {
            "operationName": "questionSolutionArticles",
            "query": list_query,
            "variables": {
                "questionSlug": title_slug,
                "first": limit,
                "orderBy": "MOST_UPVOTE"
            }
        }
        resp = self.http.post(GRAPHQL_URL, json=payload, timeout=15)
        resp.raise_for_status()
        edges = resp.json().get("data", {}).get("questionSolutionArticles", {}).get("edges", []) or []

        detail_query = """
        query solutionDetailArticle($slug: String!, $orderBy: SolutionArticleOrderBy!) {
            solutionArticle(slug: $slug, orderBy: $orderBy) {
                ... on SolutionArticleNode {
                    title
                    content
                }
            }
        }
        """
        # 通配包含 [sol-Python3] 等力扣扩展标签的代码块
        code_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
        candidates = []

        for idx, edge in enumerate(edges, 1):
            node = edge.get("node", {})
            slug = node.get("slug")
            title = node.get("title", f"题解-{idx}")
            if not slug:
                continue

            try:
                detail_resp = self.http.post(
                    GRAPHQL_URL,
                    json={
                        "operationName": "solutionDetailArticle",
                        "query": detail_query,
                        "variables": {
                            "slug": slug,
                            "orderBy": "DEFAULT"
                        }
                    },
                    timeout=15
                )
                article = detail_resp.json().get("data", {}).get("solutionArticle") or {}
                content = article.get("content", "")
                if not content:
                    continue

                blocks = code_pattern.findall(content)
                for block in blocks:
                    clean_code = block.strip()
                    if "class Solution" in clean_code and "def " in clean_code:
                        candidates.append({"article_title": title, "code": clean_code})
                        logger.info(f"✔ 成功提取到 Python3 代码 (来自: {title})")
                        break
            except Exception as e:
                logger.warning(f"获取题解 [{title}] 详情失败: {e}")

        return candidates

    def submit_code(self, title_slug: str, question_id: str, code: str, lang: str = "python3") -> str:
        """提交代码并返回 submission_id"""
        url = BASE_URL + f"/problems/{title_slug}/submit/"
        headers = {"Referer": BASE_URL + f"/problems/{title_slug}/"}
        payload = {
            "question_id": question_id,
            "lang": lang,
            "typed_code": code
        }
        resp = self.http.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"提交请求失败 ({resp.status_code}): {resp.text}")
        
        result = resp.json()
        if "submission_id" not in result:
            raise RuntimeError(f"提交未返回 submission_id: {result}")
        return str(result["submission_id"])

    def poll_check(self, submission_id: str, max_retries: int = 15) -> Tuple[bool, str]:
        """轮询判题结果"""
        check_url = BASE_URL + f"/submissions/detail/{submission_id}/check/"
        for _ in range(max_retries):
            time.sleep(2)
            resp = self.http.get(check_url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if data.get("state") == "SUCCESS":
                status = data.get("status_msg")
                return (status == "Accepted"), status
        return False, "Check Timeout"

    def run(self):
        logger.info("正在获取今日每日一题...")
        daily = self.get_daily_question()
        logger.info(f"今日题目: [{daily['frontend_id']}] {daily['title']} ({daily['title_slug']})")

        # 检查是否已完成打卡
        if daily["user_status"] == "FINISH":
            logger.info("🎉 检测到今日题目已打卡完成 (Accepted)，无需重复提交！")
            return

        logger.info("正在获取题解并提取代码...")
        candidates = self.fetch_solution_candidates(daily["title_slug"])
        if not candidates:
            raise RuntimeError("未能在高赞题解中解析出有效的 Python3 代码！")

        # 试运行模式
        if DRY_RUN:
            logger.info("[DRY_RUN] 处于调试模式，不执行真实提交。代码预览：")
            print("=" * 60)
            print(candidates[0]["code"])
            print("=" * 60)
            return

        # 校验登录凭据
        if not self.session_token or not self.csrf_token:
            logger.error("❌ 未检测到登录凭据！")
            logger.error("👉 请先运行一次: python3 get_leetcode_token.py 进行登录与凭证提取。")
            return

        # 逐个尝试候选代码直到通过
        for idx, candidate in enumerate(candidates, 1):
            logger.info(f"正在提交第 {idx}/{len(candidates)} 份题解代码...")
            try:
                sub_id = self.submit_code(
                    daily["title_slug"],
                    daily["question_id"],
                    candidate["code"],
                    lang="python3"
                )
                logger.info(f"已提交评测 (Submission ID: {sub_id})，等待判题结果...")
                
                is_accepted, status_msg = self.poll_check(sub_id)
                if is_accepted:
                    logger.info(f"🎉 打卡成功！评测结果: {status_msg}")
                    return
                else:
                    logger.warning(f"⚠️ 未通过 ({status_msg})，尝试下一篇题解...")
            except Exception as e:
                logger.error(f"提交异常: {e}")
            
            time.sleep(5)

        logger.error("所有候选代码均已尝试，本次打卡未成功。")

if __name__ == "__main__":
    bot = LeetCodeBot(session_token=LEETCODE_SESSION, csrf_token=CSRF_TOKEN)
    bot.run()
