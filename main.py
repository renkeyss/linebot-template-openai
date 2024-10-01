# -*- coding: utf-8 -*-

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
_ = load_dotenv(find_dotenv())

# Dictionary to store user message counts and reset times
user_message_counts = {}

# User daily limit
USER_DAILY_LIMIT = 50

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 查詢 OpenAI Storage Vector Store
def search_vector_store(query):
    vector_store_id = 'vs_mDCiMdkMG9zz9Y4AMZ672eNI'  # Vector Store ID
    api_key = os.getenv('OPENAI_API_KEY')  # 確保使用環境變數中正確的 API key
    
    if not api_key:
        logger.error("API key is not set")
        return None

    url = f"https://api.openai.com/v1/vector_stores/{vector_store_id}"
    
    payload = {
        "query": query
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2"
    }

    logger.info(f"Sending request to Vector Store with query: {query}")
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        logger.info(f"Response from Vector Store: {response.json()}")
        return response.json()  # 假設回應返回 JSON
    else:
        logger.error(f"Error: Failed to search Vector Store, HTTP code: {response.status_code}, error info: {response.text}")
        return None

# 使用指定的助手處理請求
async def call_assistant(user_message):
    assistant_id = 'asst_Cy9VWpQy2XiQ1wfvNlu3rst8'  # 指定助手 ID

    # 首先檢查知識庫
    vector_store_response = search_vector_store(user_message)
    knowledge_content = ""
    
    if vector_store_response and "results" in vector_store_response:
        knowledge_items = vector_store_response["results"]
        if knowledge_items:
            # 整合知識庫資料
            knowledge_content = "\n".join(item['content'] for item in knowledge_items)
    
    # 組合最終訊息
    user_message = f"{user_message}\n相關知識庫資料：\n{knowledge_content}" if knowledge_content else user_message

    # 替換成調用指定助手的邏輯
    try:
        response = await query_assistant_api(assistant_id, user_message)
        logger.info(f"Response from assistant: {response}")
        return response
    except Exception as e:
        logger.error(f"Error calling assistant: {e}")
        return "Error: 系統出現錯誤，請稍後再試。"

# 自定義函數用於調用指定助手的 API
async def query_assistant_api(assistant_id, message):
    # 這裡是調用指定助手的 API 的邏輯
    # 需要替換成實際的請求代碼
    url = f"https://your-assistant-api-endpoint/{assistant_id}"
    
    payload = {
        "message": message
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                return result['response']  # 假設回應中有 'response' 欄位
            else:
                logger.error(f"Error: Failed to call assistant API, HTTP code: {response.status}")
                return "Error: Assistant API out of service"

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
    "我是 彰化基督教醫院 內分泌暨新陳代謝科 小助理，如果您有任何關於：糖尿病、高血壓、甲狀腺的相關問題，您可以詢問我。"
    "但基本上我是由大型語言模型訓練，所以您有任何疑問建議您要向您的醫療團隊做進一步的諮詢，謝謝！"
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

        # 呼叫指定助手
        result_text = await call_assistant(user_message)
        
        # 更新用戶訊息計數
        user_message_counts[user_id]['count'] += 1

        # 回應用戶訊息
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result_text)
        )

    return 'OK'
