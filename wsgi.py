import threading, asyncio
from main import flask_app, init_db, start_bot

def run_bot():
    asyncio.run(start_bot())

init_db()
threading.Thread(target=run_bot, daemon=True).start()

app = flask_app
