from flask import Flask
from threading import Thread
import os
import time
import requests
import logging

app = Flask('')

@app.route('/')
def home():
    return "🤖 Referral Bot is Alive and Running!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    """ثغرة تنشيط ذاتية ترسل طلب كل دقيقتين لمنع سيرفر رندر من النوم"""
    app_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not app_url:
        return
    while True:
        try:
            time.sleep(120)
            requests.get(app_url)
            logging.info("Self-ping sent successfully!")
        except Exception as e:
            logging.error(f"Self-ping failed: {e}")

def keep_alive():
    t = Thread(target=run)
    t.start()
    
    if os.environ.get("RENDER_EXTERNAL_URL"):
        ping_thread = Thread(target=self_ping, daemon=True)
        ping_thread.start()
