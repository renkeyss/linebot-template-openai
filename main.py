# -*- coding: utf-8 -*-

import openai
import os
import sys
import aiohttp
import requests
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
_ = load_dotenv(find_dotenv())  # read local .env file

# Dictionary to store user message counts and reset times
user_message_counts = {}

# User daily limit
USER_DAILY_LIMIT = 5

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 檢索 Vector store 的函式
def search_file_store(query, file_id):
    api_key = os.getenv('OPENAI_API_KEY', None)
    if not api_key:
        logger.error("API key is not set")
        return None

    url = f"https://api.openai.com/v1/files/{file_id}/search"
    
    payload = {
        "query": query,
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"Sending request to File store with query: {query}")
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # 假設回應返回 JSON
    else:
        logger.error(f"Error: Failed to search File store, HTTP code: {response.status_code}, error info: {response.text}")
        return None

# 呼叫 OpenAI 助手
async def call_openai_assistant(user_message, assistant_id):
    api_key = os.getenv('OPENAI_API_KEY', None)
    if not api_key:
        logger.error("API key is not set")
        return "API key is not set."

    url = f"https://api.openai.com/v1/assistants/{assistant_id}/messages"
    
    payload = {
        "input": user_message
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    logger.info(f"Sending request to OpenAI assistant with input: {user_message}")
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        response_data = response.json()
        logger.info(f"OpenAI assistant response: {response_data}")
        return response_data['choices'][0]['message']['content']  # 假設回應返回 JSON
    else:
        logger.error(f"Error: Failed to call OpenAI assistant, HTTP code: {response.status_code}, error info: {response.text}")
        return f"Error: Failed to call OpenAI assistant. HTTP code: {response.status_code}, error info: {response.text}"

# 初始化 OpenAI API
async def call_openai_chat_api(user_message, is_classification=False):
    openai.api_key = os.getenv('OPENAI_API_KEY', None)
    assistant_id = 'asst_ShZXAJwKlokkj9rNhRi2f6pG'
    
    return await call_openai_assistant(user_message, assistant_id)

# Get channel_secret and channel_access_token from your environment variable
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
        # 檢查事件是否為 MessageEvent 並確定位訊息類型
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

        # 呼叫 OpenAI 助手（或執行其他操作）
        try:
            result_text = await call_openai_chat_api(user_message)
            logger.info(f"OpenAI assistant response: {result_text}")
        except Exception as e:
            logger.error(f"Error calling OpenAI assistant: {e}")
            result_text = "Error: 系統出現錯誤，請稍後再試。"

        # 更新用戶訊息計數
        user_message_counts[user_id]['count'] += 1

        # 回應用戶訊息
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result_text)
        )

    return 'OK'
