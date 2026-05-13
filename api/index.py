#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function 版本
文件需放在项目的 /api/index.py 目录下
Vercel 免费部署，无需服务器
"""

# 直接引用主逻辑
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot_server import handler as bot_handler
from http.server import BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        event = {
            "body": body.decode("utf-8"),
            "headers": dict(self.headers)
        }
        
        result = bot_handler(event, None)
        
        self.send_response(result.get("statusCode", 200))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result.get("body", "{}").encode("utf-8"))
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("钉钉机器人服务运行中 ✅".encode("utf-8"))
