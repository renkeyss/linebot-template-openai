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
import pinecone  # 新增 Pinecone 客戶端

# 設置日誌紀錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 讀取環境變數
_ = load_dotenv(find_dotenv())

# 新增 Pinecone 初始化
pinecone_api_key = os.getenv('PINECONE_API_KEY')  
pinecone_environment = os.getenv('PINECONE_ENVIRONMENT')
pinecone.init(api_key=pinecone_api_key, environment=pinecone_environment)  # 初始化 Pinecone

# Dictionary to store user message counts and reset times
user_message_counts = {}

# User daily limit
USER_DAILY_LIMIT = 5

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 查詢 Pinecone 向量資料庫
def search_vector_store(query):
    index_name = 'renkeyss'  # 替換為你的 Pinecone 索引名稱
    index = pinecone.Index(index_name)
    
    # 在此進行向量化查詢（這裡需要將查詢轉換為向量，通常會使用 OpenAI 的 embeddings API）
    embedding = openai.Embedding.create(input=query, model="text-embedding-ada-002")
    query_vector = embedding['data'][0]['embedding']

    logger.info(f"Querying Pinecone with vector: {query_vector}")

    # 在 Pinecone 查詢相似的向量
    response = index.query(queries=[query_vector], top_k=5, include_metadata=True)

    if response and 'matches' in response:
        logger.info(f"Response from Pinecone: {response['matches']}")
        return response['matches']  # 返回相似結果
    else:
        logger.error("Error: Failed to search Pinecone vector store")
        return None

# 呼叫 OpenAI Chat API
async def call_openai_chat_api(user_message):
    openai.api_key = os.getenv('OPENAI_API_KEY')  # 確保使用環境變數中正確的 API key
    
    assistant_id = 'asst_HVKXE6R3ZcGb6oW6fDEpbdOi'  # 指定助手 ID

    # 首先檢查知識庫
    vector_store_response = search_vector_store(user_message)
    knowledge_content = ""
    
    if vector_store_response:
        if knowledge_items := vector_store_response:
            # 整合知識庫資料
            knowledge_content = "\n".join(item['metadata']['content'] for item in knowledge_items)  # 確保有 `content` 欄位
    
    # 組合最終訊息
    user_message = f"{user_message}\n相關知識庫資料：\n{knowledge_content}" if knowledge_content else user_message

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": f"Assistant ID: {assistant_id}. 你是一個樂於助人的助手，請使用繁體中文回覆。"},
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

        # 呼叫 OpenAI 助手
        result_text = await call_openai_chat_api(user_message)
        
        # 更新用戶訊息計數
        user_message_counts[user_id]['count'] += 1

        # 回應用戶訊息
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result_text)
        )

    return 'OK'
