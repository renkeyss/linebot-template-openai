# -*- coding: utf-8 -*-

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
            "to disease, medications, endocrinology, healthcare, patient safety, or medical quality:\n\n"
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

# Fetch and search information from the specified website
async def search_website(url, query):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise HTTPException(
                    status_code=response.status,
                    detail="Failed to fetch website"
                )
            page_content = await response.text()

    soup = BeautifulSoup(page_content, 'html.parser')

    search_results = []
    for elem in soup.find_all(text=True):
        if query in elem:
            search_results.append(elem.strip())

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
    "我是彰化基督教醫院 內分泌科小助理，您有任何關於疾病、藥品、內分泌、醫療、病人安全及醫療品質的相關問題都可以問我。"
)

@app.post("/callback")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

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

        if user_id in user_message_counts:
            if datetime.now() >= user_message_counts[user_id]['reset_time']:
                reset_user_count(user_id)
        else:
            reset_user_count(user_id)

        if user_message_counts[user_id]['count'] >= USER_DAILY_LIMIT:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您今天的用量已經超過，請明天再詢問。")
            )
            continue

        user_message = event.message.text

        if "介紹" in user_message or "你是誰" in user_message:
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=introduction_message)
            )
            continue

        if user_message == "門診表":
            user_state[user_id] = "querying_doctor"
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您要查詢哪位醫師的門診時間表？")
            )
            continue

        if user_message == "衛教":
            user_state[user_id] = "querying_education"
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您要查詢哪方面的衛教？")
            )
            continue

        if user_id in user_state:
            if user_state[user_id] == "querying_doctor":
                del user_state[user_id]
                search_results = await search_website("https://www1.cch.org.tw/opd/Service-e.aspx", user_message)
                if search_results:
                    result_text = "\n".join(search_results[:5])  # limit to 5 results
                    response_text = f"以下是與您查詢的醫師門診時間表相關的資訊：\n\n{result_text}\n\n詳情請見網址：https://www1.cch.org.tw/opd/Service-e.aspx"
                else:
                    response_text = "未能找到與您查詢的醫師門診時間表相關的資訊，請換一個醫師姓名再試。"
                await line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=response_text)
                )
                continue

            if user_state[user_id] == "querying_education":
                del user_state[user_id]
                search_results = await search_website("https://www.cch.org.tw/knowledge.aspx?pID=1", user_message)
                if search_results:
                    result_text = "\n".join(search_results[:5])  # limit to 5 results
                    response_text = f"以下是與您查詢的衛教相關的資訊：\n\n{result_text}\n\n詳情請見網址：https://www.cch.org.tw/knowledge.aspx?pID=1"
                else:
                    response_text = "未能找到與您查詢的衛教相關的資訊，請換一個關鍵字再試。"
                await line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=response_text)
                )
                continue

        classification_response = call_openai_chat_api(user_message, is_classification=True)

        if "non-relevant" in classification_response.lower():
            await line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您的問題已經超出我的功能，我無法進行回覆，請重新提出您的問題。")
            )
            continue

        result = call_openai_chat_api(user_message)

        user_message_counts[user_id]['count'] += 1

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result)
        )

    return 'OK'

# Close aiohttp session when the application stops
@app.on_event("shutdown")
async def shutdown_event():
    await session.close()
