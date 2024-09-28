# -*- coding: utf-8 -*-

import openai
import os
import sys
import aiohttp
import asyncio
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

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 設置日誌紀錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 讀取環境變數
_ = load_dotenv(find_dotenv())

# Google Drive API 設置
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# Dictionary to store user message counts and reset times
user_message_counts = {}
USER_DAILY_LIMIT = 5

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# 獲取 Google Drive 中的資料夾內容
async def get_drive_folder_contents(folder_id):
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, lambda: drive_service.files().list(
            q=f"'{folder_id}' in parents", 
            pageSize=10, 
            fields="files(id, name)"
        ).execute())
        items = results.get('files', [])
        
        if not items:
            return "此資料夾是空的。"
        
        return "\n".join([f"{item['name']} (ID: {item['id']})" for item in items])
    
    except HttpError as e:
        logger.error(f"HTTP error fetching Google Drive folder contents: {e}")
        return "無法獲取資料夾內容。"
    except Exception as e:
        logger.error(f"Error fetching Google Drive folder contents: {e}")
        return "無法獲取資料夾內容。"

# Initialize LINE Bot Messaging API
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)

channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)

if channel_secret is None:
    logger.error('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

# 入口訊息
introduction_message = (
    "我是彰化基督教醫院 內分泌科小助理，您有任何關於：糖尿病、高血壓及內分泌的相關問題都可以問我。"
)

@app.post("/callback")
async def handle_callback(request: Request):
    # 立即返回成功的 HTTP 200 響應
    signature = request.headers['X-Line-Signature']
    body = await request.body()
    logger.info(f"Received webhook body: {body.decode()}")

    try:
        # 解析 webhook 的事件
        events = parser.parse(body.decode(), signature)

        # 處理所有事件
        for event in events:
            # 確保只是處理訊息事件
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

            # 獲取 Google Drive 資料夾內容
            if "資料夾內容" in user_message:
                folder_id = "117414381559448263801"  # 硬編碼資料夾 ID
                folder_content = await get_drive_folder_contents(folder_id)
                result_text = f"資料夾內容：\n{folder_content}"
            else:
                # 在這裡調用 OpenAI 的函數來處理用戶請求
                result_text = await call_openai_chat_api(user_message)

            # 更新用戶訊息計數
            user_message_counts[user_id]['count'] += 1

            # 回應用戶訊息
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=result_text)
            )

    except InvalidSignatureError:
        logger.error("Invalid signature")
        return HTTPException(status_code=400, detail="Invalid signature")  # 返回簽名無效的錯誤

    except Exception as e:
        logger.error(f"Error processing the request: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error") # 返回500錯誤響應

    return HTTPException(status_code=200, detail='OK')  # 返回成功響應
