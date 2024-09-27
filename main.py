from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, 
    TextMessage, 
    TextSendMessage)
import openai
import os
import datetime

# 設定 LINE Bot 相關資訊
api = LineBotApi(os.getenv('LINE_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))

# 設定 OpenAI API 密鑰
openai.api_key = os.getenv("OPENAI_API_KEY")

# 建立 Flask 應用程序
app = Flask(__name__)

user_questions = {}

@app.route("/", methods=['POST'])
def callback():
    # 取得 X-Line-Signature 表頭電子簽章內容
    signature = request.headers.get('X-Line-Signature')

    # 以文字形式取得請求內容
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 比對電子簽章並處理請求內容
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("電子簽章錯誤, 請檢查密鑰是否正確？")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    current_date = datetime.date.today()

    if user_id not in user_questions:
        user_questions[user_id] = {}

    user_data = user_questions[user_id]

    if user_data.get("date") != current_date:
        user_data["date"] = current_date
        user_data["count"] = 0

    if user_data["count"] >= 10:
        reply_text = '您目前的使用量已用完，請明天再詢問，如有任何問題請致電 04-7238595 分機 3239 我們將有專人為您服務'
    else:
        user_data["count"] += 1

        # 判斷使用者的問題是否為內分泌科相關問題
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "請判斷以下內容是否與內分泌科有關："},
                {"role": "user", "content": event.message.text}
            ]
        )

        # 獲取回應並轉為小寫，進行判斷
        is_medical_related = response.choices[0].message.get('content', '').strip().lower()

        # 檢查是否是相關問題
        if "是" in is_medical_related or "有關" in is_medical_related:
            # 若是內分泌科相關問題，繼續處理
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "您正在與彰化基督教醫院內分泌科小助理對話。"},
                    {"role": "user", "content": event.message.text}
                ]
            )

            # 取得回覆
            reply_text = response.choices[0].message.get('content', '').strip()
            if reply_text == '':
                reply_text = '出現錯誤，無法提供回覆。請稍後再試。'
        else:
            # 若不相關，回覆特定訊息
            reply_text = '您所問的問題，不是內分泌科的相關問題，所以我無法回覆您，謝謝。'

    # 最終回覆
    api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
