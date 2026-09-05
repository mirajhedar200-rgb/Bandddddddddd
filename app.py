import os
import asyncio
from flask import Flask, request, jsonify
from flask_socketio import SocketIO
from telegram import Update
from bot import build_application
from db import init_db

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "secret_key_123")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# تهيئة البوت وتطبيقه
bot_app = build_application()

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "Server is running", "ai_enabled": True}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        
        # تشغيل معالجة التليغرام في النمط التزامني لـ Flask
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_app.process_update(update))
        loop.close()
        
        return "OK", 200

@socketio.on('connect')
def handle_connect():
    print("Client connected to SocketIO")

if __name__ == "__main__":
    init_db()
    # تهيئة Webhook للتليغرام
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
    
    port = int(os.getenv("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
