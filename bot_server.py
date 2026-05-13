#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉群机器人自动回复服务
支持：知识库FAQ匹配 + AI智能补充
部署平台：腾讯云函数 SCF / 阿里云函数计算 / Vercel（均有免费额度）
"""

import json
import os
import re
import hashlib
import hmac
import base64
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ==========================================
# 配置区（部署时修改这些变量）
# ==========================================
CONFIG = {
    # 钉钉机器人安全设置 - 加签密钥（在钉钉开发者后台获取）
    "DINGTALK_APP_SECRET": os.environ.get("DINGTALK_APP_SECRET", "your_app_secret_here"),
    
    # 钉钉机器人 AppKey（可选，用于主动发消息）
    "DINGTALK_APP_KEY": os.environ.get("DINGTALK_APP_KEY", ""),
    "DINGTALK_APP_SECRET_KEY": os.environ.get("DINGTALK_APP_SECRET_KEY", ""),
    
    # AI大模型配置（使用OpenAI兼容接口，可换成任意大模型）
    # 推荐：腾讯混元（免费额度充足）或阿里通义千问
    "AI_API_URL": os.environ.get("AI_API_URL", "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"),
    "AI_API_KEY": os.environ.get("AI_API_KEY", "your_ai_api_key_here"),
    "AI_MODEL": os.environ.get("AI_MODEL", "hunyuan-turbo"),
    
    # 知识库文件路径
    "KB_FILE": os.path.join(os.path.dirname(__file__), "knowledge_base.json"),
    
    # 机器人名称（在群里@它时用）
    "BOT_NAME": "小助手",
    
    # 公司名称（AI回答时用于提示词）
    "COMPANY_NAME": os.environ.get("COMPANY_NAME", "公司"),
    
    # 匹配分数阈值（0-1，越高越严格）
    "MATCH_THRESHOLD": 0.3,
}

# ==========================================
# 知识库加载与FAQ匹配
# ==========================================
_knowledge_base = None

def load_knowledge_base():
    """加载知识库"""
    global _knowledge_base
    if _knowledge_base is not None:
        return _knowledge_base
    
    try:
        kb_path = CONFIG["KB_FILE"]
        if os.path.exists(kb_path):
            with open(kb_path, "r", encoding="utf-8") as f:
                _knowledge_base = json.load(f)
        else:
            # 内嵌默认知识库（当文件不存在时）
            _knowledge_base = {"faqs": []}
    except Exception as e:
        print(f"加载知识库失败: {e}")
        _knowledge_base = {"faqs": []}
    
    return _knowledge_base

def search_faq(question: str) -> dict | None:
    """
    在知识库中搜索最匹配的FAQ
    返回: {"answer": str, "score": float} 或 None
    """
    kb = load_knowledge_base()
    faqs = kb.get("faqs", [])
    
    if not faqs:
        return None
    
    question_lower = question.lower()
    best_match = None
    best_score = 0.0
    
    for faq in faqs:
        score = 0.0
        keywords = faq.get("keywords", [])
        
        # 关键词匹配得分
        matched_keywords = 0
        for kw in keywords:
            if kw in question_lower:
                matched_keywords += 1
        
        if keywords:
            score = matched_keywords / len(keywords)
            # 匹配多个关键词时额外加分
            if matched_keywords >= 2:
                score = min(1.0, score + 0.2)
            # 只要匹配一个关键词，给一个基础分
            if matched_keywords >= 1:
                score = max(score, 0.4)
        
        # 问题标题匹配（逐字符匹配）
        faq_question = faq.get("question", "").lower()
        for char in question_lower:
            if len(char.strip()) > 0 and char in faq_question:
                score = min(1.0, score + 0.02)
        
        if score > best_score:
            best_score = score
            best_match = faq
    
    if best_match and best_score >= CONFIG["MATCH_THRESHOLD"]:
        return {
            "answer": best_match.get("answer", ""),
            "score": best_score,
            "faq_id": best_match.get("id")
        }
    
    return None

# ==========================================
# AI大模型调用
# ==========================================
def ask_ai(question: str, context: str = "") -> str:
    """
    调用AI大模型回答问题
    支持任何OpenAI兼容接口
    """
    api_key = CONFIG["AI_API_KEY"]
    if not api_key or api_key == "your_ai_api_key_here":
        return "⚠️ AI服务暂未配置，请联系管理员。\n\n如需人工解答，请@店长或HR。"
    
    system_prompt = f"""你是{CONFIG['COMPANY_NAME']}的门店智能助手「{CONFIG['BOT_NAME']}」。
你的职责是帮助门店员工解答业务操作规范相关问题。

回答要求：
1. 回答要简洁、准确、实用
2. 使用Markdown格式，适当使用emoji让回答更易读
3. 如果问题超出业务范围，礼貌说明并引导找相关负责人
4. 不要编造公司政策，对不确定的内容说"请以最新公司文件为准"
5. 回答控制在200字以内

{f"参考信息：{context}" if context else ""}"""
    
    payload = {
        "model": CONFIG["AI_MODEL"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        "max_tokens": 500,
        "temperature": 0.3
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        req = urllib.request.Request(
            CONFIG["AI_API_URL"],
            data=data,
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    
    except Exception as e:
        print(f"AI调用失败: {e}")
        return f"🤖 智能助手暂时无法回答这个问题，请联系店长或相关负责人。"

# ==========================================
# 消息处理核心逻辑
# ==========================================
def process_message(user_name: str, question: str) -> str:
    """
    处理员工的问题，返回回答
    流程：FAQ匹配 → AI补充 → 默认回复
    """
    question = question.strip()
    
    if not question:
        return f"你好！我是{CONFIG['BOT_NAME']} 😊\n\n请直接提问，我可以解答门店业务操作规范相关问题！\n\n💡 例如：\n• 怎么申请请假？\n• 退货退款流程是什么？\n• 考勤迟到怎么处理？"
    
    # 问候语处理
    greetings = ["你好", "hello", "hi", "帮助", "help", "菜单", "功能"]
    if any(g in question.lower() for g in greetings) and len(question) < 10:
        return f"""你好，{user_name}！我是{CONFIG['BOT_NAME']} 👋

我可以帮你解答以下问题：
📋 考勤打卡规定
📅 请假申请流程  
💰 费用报销流程
🏪 收银操作规范
📦 库存管理规范
🤝 客诉处理流程
💳 薪资绩效说明
🔧 系统故障处理

直接输入你的问题就好！"""
    
    print(f"[{datetime.now()}] 收到问题 - 用户: {user_name}, 问题: {question}")
    
    # 第一步：搜索知识库
    faq_result = search_faq(question)
    
    if faq_result and faq_result["score"] >= 0.5:
        # 高置信度：直接返回FAQ答案
        answer = faq_result["answer"]
        print(f"FAQ匹配成功，得分: {faq_result['score']:.2f}")
        return answer
    
    elif faq_result and faq_result["score"] >= CONFIG["MATCH_THRESHOLD"]:
        # 中等置信度：FAQ答案 + AI补充
        faq_answer = faq_result["answer"]
        ai_supplement = ask_ai(question, context=f"参考FAQ：{faq_answer}")
        print(f"FAQ部分匹配（得分:{faq_result['score']:.2f}），结合AI回答")
        # 返回FAQ答案（已经够完整了）
        return faq_answer
    
    else:
        # 未匹配到FAQ：调用AI
        print("未找到FAQ匹配，调用AI")
        ai_answer = ask_ai(question)
        footer = "\n\n---\n💡 *如需查看更多规范，请联系HR或店长*"
        return ai_answer + footer

# ==========================================
# 钉钉签名验证
# ==========================================
def verify_dingtalk_sign(timestamp: str, sign: str) -> bool:
    """验证钉钉机器人消息签名"""
    app_secret = CONFIG["DINGTALK_APP_SECRET"]
    if not app_secret or app_secret == "your_app_secret_here":
        # 未配置签名验证，跳过（仅测试时）
        return True
    
    try:
        string_to_sign = f"{timestamp}\n{app_secret}"
        hmac_code = hmac.new(
            app_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        expected_sign = base64.b64encode(hmac_code).decode("utf-8")
        return sign == expected_sign
    except Exception:
        return False

# ==========================================
# 主入口函数（适配多种云函数格式）
# ==========================================
def handler(event, context=None):
    """
    云函数入口
    兼容：腾讯SCF / 阿里FC / AWS Lambda
    """
    try:
        # 解析请求体
        if isinstance(event, dict):
            # 腾讯SCF格式
            body_str = event.get("body", "{}")
            if isinstance(body_str, bytes):
                body_str = body_str.decode("utf-8")
            
            # 签名验证
            headers = event.get("headers", {})
            timestamp = headers.get("timestamp", headers.get("x-timestamp", ""))
            sign = headers.get("sign", headers.get("x-signature", ""))
            
            if timestamp and sign:
                if not verify_dingtalk_sign(timestamp, sign):
                    return {"statusCode": 403, "body": "签名验证失败"}
            
            body = json.loads(body_str) if body_str else {}
        else:
            body = {}
        
        # 提取消息内容
        msg_type = body.get("msgtype", "")
        
        if msg_type == "text":
            content = body.get("text", {}).get("content", "").strip()
            sender_nick = body.get("senderNick", "同事")
            
            # 去除@机器人的部分
            bot_name = CONFIG["BOT_NAME"]
            content = re.sub(r"@\S+\s*", "", content).strip()
            
            if content:
                answer = process_message(sender_nick, content)
                
                # 构造回复（Markdown格式）
                response_body = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": f"{bot_name}回复",
                        "text": f"**{sender_nick}，你好！**\n\n{answer}"
                    }
                }
                
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(response_body, ensure_ascii=False)
                }
        
        # 默认响应（非文本消息）
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "msgtype": "text",
                "text": {"content": f"你好！我是{CONFIG['BOT_NAME']}，目前只支持文字提问哦 😊"}
            }, ensure_ascii=False)
        }
    
    except Exception as e:
        print(f"处理消息出错: {e}")
        import traceback
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


# ==========================================
# 本地测试入口
# ==========================================
if __name__ == "__main__":
    import sys
    # Windows控制台UTF-8输出
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    
    print("=== 钉钉机器人本地测试模式 ===")
    print(f"当前时间: {datetime.now()}")
    print()
    
    test_questions = [
        "怎么申请请假？",
        "收银操作有什么注意事项？",
        "工资什么时候发？",
        "POS机坏了怎么办？",
        "顾客来投诉要怎么处理",
    ]
    
    for q in test_questions:
        print(f"[问题] {q}")
        answer = process_message("测试员工", q)
        print(f"[回答]\n{answer}")
        print("-" * 60)
