# -*- coding: utf-8 -*-

import openai
import os
import sys
import aiohttp
from datetime import datetime, timedelta
from fastapi import Request, FastAPI, HTTPException
from linebot import (
    AsyncLineBotApi, WebhookParser
)
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
)
from dotenv import load_dotenv, find_dotenv
import logging

# 設置日誌紀錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 讀取環境變數
_ = load_dotenv(find_dotenv())

# Dictionary to store user message counts and reset times
user_message_counts = {}

# User daily limit
USER_DAILY_LIMIT = 5

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 執行網頁檢索
async def web_search(query):
    # 將此替換為實際的搜尋引擎 API 的 URL
    search_url = f"https://api.example.com/search?q={query}"  
    headers = {
        "Authorization": f"Bearer {os.getenv('SEARCH_API_KEY')}",  # 從環境變數獲取 API 金鑰
        "Content-Type": "application/json"
    }

    logger.info(f"Sending request to web search with query: {query}")

    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                logger.info(f"Response from web search: {result}")
                return result  # 假設回應返回 JSON
            else:
                logger.error(f"Error: Failed to search web, HTTP code: {response.status}, error info: {await response.text()}")
                return None

# 呼叫 OpenAI Chat API
async def call_openai_chat_api(user_message):
    openai.api_key = os.getenv('OPENAI_API_KEY')  # 確保使用環境變數中正確的 API key
    
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "你是一個樂於助人的助手，請使用繁體中文回覆。"},
                {"role": "user", "content": user_message}
            ]
        )
        logger.info(f"Response from OpenAI assistant: {response.choices[0]['message']['content']}")
        return response.choices[0]['message']['content']
    except Exception as e:
        logger.error(f"Error calling OpenAI assistant: {e}")
        return "Error: 系統出現錯誤，請稍後再試。"

# 獲取 channel_secret 和 channel_access_token
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
if channel_secret is None:
    logger.error('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

# Initialize LINE Bot Messaging API
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

# Introduction message
introduction_message = (
    "我是彰化基督教醫院 內分泌科小助理，您有任何關於：糖尿病、高血壓及內分泌的相關問題都可以問我。"
)

@app.post("/callback")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()
    logger.info(f"Request body: {body.decode()}")
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessage):
            continue

        user_id = event.source.user_id
        user_message = event.message.text

        logger.info(f"Received message from user {user_id}: {user_message}")

        # 檢查訊息計數是否需要重置
        if user_id in user_message_counts:
            if datetime.now() >= user_message_counts[user_id]['reset_time']:
                reset_user_count(user_id)
        else:
            reset_user_count(user_id)

        # 檢查用戶是否超過每日限制
        if user_message_counts[user_id]['count'] >= USER_DAILY_LIMIT:
            logger.info(f"User {user_id} exceeded daily limit")
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您今天的用量已經超過，請明天再詢問。")
            )
            continue

        # 處理特殊請求（如介紹）
        if "介紹" in user_message or "你是誰" in user_message:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=introduction_message)
            )
            continue
        
        # 執行網頁檢索
        search_results = await web_search(user_message)
        search_content = ""
        
        if search_results and "results" in search_results:
            search_items = search_results["results"]
            if search_items:
                search_content = "\n".join(item['title'] for item in search_items)  # 假設每個項目有一個標題
        
        # 組合最終回覆
        if search_content:
            result_text = f"網頁檢索結果：\n{search_content}"
        else:
            result_text = await call_openai_chat_api(user_message)

        # 更新用戶訊息計數
        user_message_counts[user_id]['count'] += 1

        # 回應用戶訊息
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result_text)
        )

    return 'OK'
