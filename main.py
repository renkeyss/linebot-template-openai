# -*- coding: utf-8 -*-
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
# https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import openai
import os
import sys
import aiohttp
from datetime import datetime, timedelta
from fastapi import Request, FastAPI, HTTPException
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv, find_dotenv
from bs4 import BeautifulSoup

_ = load_dotenv(find_dotenv())  # read local .env file

# Dictionary to store user message counts and reset times
user_message_counts = {}
user_state = {}  # Dictionary to keep track of user states

# User daily limit
USER_DAILY_LIMIT = 5

def reset_user_count(user_id):
    user_message_counts[user_id] = {
        'count': 0,
        'reset_time': datetime.now() + timedelta(days=1)
    }

# Initialize OpenAI API
def call_openai_chat_api(user_message, is_classification=False):
    openai.api_key = os.getenv('OPENAI_API_KEY', None)

    if is_classification:
        prompt = (
            "Classify the following message as relevant or non-relevant "
            "to Changhua Christian Hospital or any of its departments, services, or doctors:\n\n"
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

# Fetch and search information from the hospital website
async def search_hospital_website(query):
    urls = [
        "https://www1.cch.org.tw/opd/Service-e.aspx",
        "https://www.cch.org.tw/knowledge.aspx?pID=1"
    ]
    search_results = []

    async with aiohttp.ClientSession() as session:
        for url in urls:
            async with session.get(url) as response:
                if response.status == 200:
                    page_content = await response.text()
                    soup = BeautifulSoup(page_content, 'html.parser')
                    results = [elem.strip() for elem in soup.find_all(text=True) if query in elem]
                    search_results.extend(results)
    
    return search_results

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
    "我是彰化基督教醫院 內分泌科小助理，您有任何關於彰化基督教醫院及其科別、服務、或醫師的相關問題都可以問我。"
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
        classification_response = call_openai_chat_api(user_message, is_classification=True)

        # Check if the classification is not relevant
        if "non-relevant" in classification_response.lower():
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您的問題已經超出我的功能範圍。我只能回答有關彰化基督教醫院及其科別、服務、或醫師的問題。請重新提出您的問題。")
            )
            continue

        # Perform web search for the query
        search_results = await search_hospital_website(user_message)
        if search_results:
            result_text = "\n".join(search_results[:5])  # limiting to 5 results
            response_text = f"以下是與您查詢的關鍵字相關的資訊：\n\n{result_text}\n\n詳情請參考：https://www1.cch.org.tw/opd/Service-e.aspx 或 https://www.cch.org.tw/knowledge.aspx?pID=1"
        else:
            response_text = "未能找到與您查詢的關鍵字相關的資訊，請換一個關鍵字再試。"

        # Increase user's message count
        user_message_counts[user_id]['count'] += 1

        # Reply with the search results
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response_text)
        )

    return 'OK'

# Close aiohttp session when the application stops
@app.on_event("shutdown")
async def shutdown_event():
    await session.close()
