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

# Initialize OpenAI API key
openai.api_key = os.getenv('OPENAI_API_KEY', None)

def call_openai_assistant_api(user_message):
    assistant_id = "asst_HVKXE6R3ZcGb6oW6fDEpbdOi"  # Your Assistant ID
    
    messages = [
        {"role": "system", "content": f"Assistant ID: {assistant_id}. 你是一個樂於助人的助手，請使用繁體中文回覆。"},
        {"role": "user", "content": user_message},
    ]

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages
    )

    return response.choices[0]['message']['content']

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

        # Call the OpenAI Assistant API with the user's message
        result = call_openai_assistant_api(user_message)

        # Increment user's message count
        user_message_counts[user_id]['count'] += 1

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result)
        )

    return 'OK'
