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
def search_vector_store(query, vector_store_id):
    openai.api_key = os.getenv('OPENAI_API_KEY', None)
    
    url = f"https://api.openai.com/v1/vector_stores/{vector_store_id}/search"
    
    payload = {
        "query": query,
    }
    
    headers = {
        "Authorization": f"Bearer {openai.api_key}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # 假設回應返回 JSON
    else:
        raise Exception(f"錯誤: 檢索 Vector store 失敗，HTTP 代碼：{response.status_code}, 錯誤信息：{response.text}")

async def call_openai_chat_api(user_message, is_classification=False):
    openai.api_key = os.getenv('OPENAI_API_KEY', None)
    
    if is_classification:
        # Use a special prompt for classification
        prompt = (
            "Classify the following message as relevant or non-relevant "
            "to medical, endocrinology, medications, medical quality, or patient safety:\n\n"
            f"{user_message}"
        )
        messages = [
            {"role": "system", "content": "你是一個樂於助人的助手。"},
            {"role": "user", "content": prompt},
        ]
    else:
        messages = [
            {"role": "system", "content": "你是一個樂於助人的助手。請使用繁體中文回覆。"},
            {"role": "user", "content": user_message},
        ]

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages
    )

    return response.choices[0].message['content']

# Get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
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
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessage):
            continue

        user_id = event.source.user_id

        # Check if user_ids's count is to be reset
        if user_id in user_message_counts:
            if datetime.now() >= user_message_counts[user_id]['reset_time']:
                reset_user_count(user_id)
        else:
            reset_user_count(user_id)

        # Check if user exceeded daily limit
        if user_message_counts[user_id]['count'] >= USER_DAILY_LIMIT:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您今天的用量已經超過，請明天再詢問。")
            )
            continue

        user_message = event.message.text

        # Check if the user is asking for an introduction
        if "介紹" in user_message or "你是誰" in user_message:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=introduction_message)
            )
            continue

        # Classify the message
        classification_response = await call_openai_chat_api(user_message, is_classification=True)

        # Check if the classification is not relevant
        if "non-relevant" in classification_response.lower():
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您的問題已經超出我的功能，我無法進行回覆，請重新提出您的問題。")
            )
            continue

        # 在此處調用 Vector store 檢索函式
        vector_store_id = "vs_O4EC1xmZuHy3WiSlcmklQgsR"
        search_result = search_vector_store(user_message, vector_store_id)
        
        # 假設 search_result 包含您需要的更詳盡的回答資訊
        # 在此簡化處理，只返回檢索結果的簡單文字表示
        if search_result:
            result = f"檢索結果: {search_result}"
        else:
            result = await call_openai_chat_api(user_message)

        # Increment user's message count
        user_message_counts[user_id]['count'] += 1

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result)
        )

    return 'OK'
