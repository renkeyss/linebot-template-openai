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

# 呼叫 OpenAI 嵌入 API
async def call_openai_embedding_api(user_message):
    openai.api_key = os.getenv('OPENAI_API_KEY')  # 確保使用環境變數中正確的 API key

    try:
        embedding_response = await openai.Embedding.acreate(
            model="text-embedding-ada-002",
            input=user_message
        )
        return embedding_response['data'][0]['embedding']  # 取得數據的嵌入
    except Exception as e:
        logger.error(f"Error calling OpenAI embedding API: {e}")
        return None

# 查詢 OpenAI Storage Vector Store
def search_vector_store(query_embedding):
    vector_store_id = 'vs_bN5apQ49HPaIqMFgXk5mbg5i'  # Vector Store ID
    api_key = os.getenv('OPENAI_API_KEY')  # 確保使用環境變數中正確的 API key
    
    if not api_key:
        logger.error("API key is not set")
        return None

   url = f"https://https://platform.openai.com/storage/vector_stores/{vector_store_id}/search"  # 假設這是正確的 URL
    
    payload = {
        "embedding": query_embedding,  # 確保嵌入是列表格式
        "k": 5  # 返回前 5 個相似結果
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2"  # 包含 OpenAI-Beta 標頭
    }

    logger.info(f"Sending request to Vector Store with query embedding: {query_embedding}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # 檢查如果回應是個錯誤
        logger.info("Successfully retrieved from Vector Store.")
        return response.json()  # 假設回應返回 JSON
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}")
        logger.error(f"Response: {response.text}")
        return None
    except Exception as e:
        logger.error(f"Error: Failed to search Vector Store, {e}")
        return None

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

        # 呼叫 OpenAI 嵌入 API
        query_embedding = await call_openai_embedding_api(user_message)
        
        if query_embedding is None:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="無法生成嵌入，請稍後重試。")
            )
            continue
        
        logger.info(f"Generated embedding: {query_embedding}")  # 記錄生成的嵌入
        
        # 查詢向量儲存
        vector_store_response = search_vector_store(query_embedding)

        if vector_store_response is None:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="無法查詢向量儲存，請稍後重試。")
            )
            continue
        
        logger.info(f"Response from Vector Store: {vector_store_response}")  # 記錄查詢結果

        knowledge_content = ""
        if vector_store_response and "results" in vector_store_response:
            knowledge_items = vector_store_response["results"]
            if knowledge_items:
                knowledge_content = "\n".join(item['content'] for item in knowledge_items)
            else:
                logger.warning("No items found in vector store results.")
        else:
            logger.error("No results found in the response from vector store.")

        # 構建最終響應
        response_text = knowledge_content if knowledge_content else "沒有找到相關資料。"

        # 更新用戶訊息計數
        user_message_counts[user_id]['count'] += 1

        # 回應用戶訊息
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response_text)
        )

    return 'OK'
