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

# 查詢 OpenAI Storage Vector Store
def search_vector_store(query):
    vector_store_id = 'vs_O4EC1xmZuHy3WiSlcmklQgsR'  # Vector Store ID
    api_key = os.getenv("OPENAI_API_KEY")  # 確保使用環境變數中正確的 API key
    
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
        return response.json()  
    else:
        logger.error(f"Error: Failed to search Vector Store, HTTP code: {response.status_code}, error info: {response.text}")
        return None

# 呼叫 OpenAI Chat API
async def call_openai_chat_api(user_message):
    openai.api_key = os.getenv("OPENAI_API_KEY")  # 確保使用環境變數中正確的 API key
    
    assistant_id = 'asst_HVKXE6R3ZcGb6oW6fDEpbdOi'  # 指定助手 ID

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

# 確認後續程式碼和環境變數設定保持不變
# 省略其餘代碼....
