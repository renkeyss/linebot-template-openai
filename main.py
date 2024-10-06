# -*- coding: utf-8 -*-

import openai
import os
import aiohttp
from datetime import datetime, timedelta
from fastapi import Request, FastAPI, HTTPException
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv, find_dotenv
import logging

# 設置日誌紀錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 讀取環境變數
load_dotenv(find_dotenv())

# 用戶消息計數與重置時間
user_message_counts = {}

# 每日訊息限制
USER_DAILY_LIMIT = 30

# 重設用戶計數
def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 呼叫 OpenAI Chat API
async def call_openai_chat_api(user_message):
    openai.api_key = os.getenv('OPENAI_API_KEY')  # 使用環境變數中的 API key
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一個樂於助人的助手，請使用繁體中文回覆。"},
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0]['message']['content']
    except Exception as e:
        logger.error(f"Error calling OpenAI assistant: {e}")
        return "Error: 系統出現錯誤，請稍後再試。"

# 初始化 LINE Bot API
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(os.getenv('ChannelAccessToken'), async_http_client)
parser = WebhookParser(os.getenv('ChannelSecret'))

# 介紹訊息
introduction_message = (
    "我是 彰化基督教醫院 內分泌暨新陳代謝科 小助理，如果您有任何相關問題，請詢問我。"
    "對於疑問請諮詢醫療團隊，謝謝！"
)

@app.post("/callback")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']
    body = (await request.body()).decode()
    
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            user_id = event.source.user_id
            user_message = event.message.text
            
            # 重設計數
            if user_id in user_message_counts and datetime.now() >= user_message_counts[user_id]['reset_time']:
                reset_user_count(user_id)
            elif user_id not in user_message_counts:
                reset_user_count(user_id)

            # 檢查每日限制
            if user_message_counts[user_id]['count'] >= USER_DAILY_LIMIT:
                await line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="您今天的用量已經超過，請明天再詢問。")
                )
                continue

            # 特殊請求（如介紹）
            if "你是誰" in user_message or "你是" in user_message:
                await line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=introduction_message)
                )
                continue

            # 呼叫 OpenAI 助手
            result_text = await call_openai_chat_api(user_message)

            # 更新計數
            user_message_counts[user_id]['count'] += 1

            # 回覆用戶訊息
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=result_text)
            )

    return 'OK'
