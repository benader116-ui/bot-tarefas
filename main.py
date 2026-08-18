import logging
import os
import sqlite3
import datetime
import threading
import tempfile

from faster_whisper import WhisperModel
import dateparser.search
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from flask import Flask, request, session, redirect, render_template_string

# ─── Configurações ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEB_PASSWORD   = os.environ.get("WEB_PASSWORD", "tarefas123")
SECRET_KEY     = os.environ.get("SECRET_KEY", "chave-secreta-flask")
PORT           = int(os.environ.get("PORT", 8080))
DB_PATH        = "tasks.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Banco de dados ───────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT NOT NULL,
                transcription TEXT NOT NULL,
                due_date      TEXT,
                done          INTEGER DEFAULT 0
            )
        """)
        conn.commit()

def save_task(transcription, due_date):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tasks (created_at, transcription, due_date) VALUES (?, ?, ?)",
            (datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), transcription, due_date),
        )
        conn.commit()

def get_tasks():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT id, created_at, transcription, due_date, done FROM tasks ORDER BY id DESC"
        ).fetchall()

def toggle_done(task_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,))
        conn.commit()

def delete_task(task_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

# ─── Whisper ──────────────────────────────────────────────────────
log.info("Carregando modelo Whisper...")
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
log.info("Modelo pronto.")

# ─── Bot Telegram ─────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙️ Recebi! Transcrevendo...")

    tg_file = await context.bot.get_file(update.message.voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        segments, _ = whisper_model.transcribe(tmp_path, language="pt")
        transcription = " ".join(s.text for s in segments).strip()
    finally:
        os.unlink(tmp_path)

    if not transcription:
        await update.message.reply_text("❌ Não consegui entender o áudio. Tente novamente.")
        return

    due_date = None
    hits = dateparser.search.search_dates(transcription, languages=["pt"])
    if hits:
        due_date = hits[0][1].strftime("%d/%m/%Y %H:%M")

    save_task(transcription, due_date)

    reply = f"✅ *Tarefa adicionada!*\n\n📝 {transcription}"
    if due_date:
        reply += f"\n📅 {due_date}"

    await update.message.reply_text(reply, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Olá! 👋\nMande um *áudio* com sua tarefa e eu vou adicioná-la à lista.",
        parse_mode="Markdown"
    )

# ─── Interface web ────────────────────────────────────────────────
flask_app = Flask(__name__)
flask_app.secret_key = SECRET_KEY

LOGIN_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Minhas Tarefas</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, sans-serif; background: #f0f2f5;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; }
    .card { background: white; border-radius: 16px; padding: 40px;
            box-shadow: 0 4px 24px rgba(0,0,0,.08); width: 100%; max-width: 360px; }
    h1 { font-size: 1.5rem; color: #1a1a2e; margin-bottom: 8px; }
    p  { color: #666; margin-bottom: 28px; font-size: .9rem; }
    input { width: 100%; padding: 12px 16px; border: 2px solid #e8e8e8;
            border-radius: 10px; font-size: 1rem; outline: none; }
    input:focus { border-color: #5b5ef4; }
    button { width: 100%; margin-top: 12px; padding: 13px; background: #5b5ef4;
             color: white; border: none; border-radius: 10px;
             font-size: 1rem; cursor: pointer; font-weight: 600; }
    button:hover { background: #4a4dd3; }
    .error { color: #e53e3e; font-size: .85rem; margin-top: 10px; text-align: center; }
  </style>
</head>
<body>
  <div class="card">
    <h1>📋 Minhas Tarefas</h1>
    <p>Entre com sua senha para ver a lista</p>
    <form method="POST">
      <input type="password" name="password" placeholder="Senha" autofocus>
      <button type="submit">Entrar</button>
      {% if error %}<p class="error">Senha incorreta</p>{% endif %}
    </form>
  </div>
</body>
</html>"""

TASKS_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Minhas Tarefas</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, sans-serif; background: #f0f2f5; padding: 24px 16px; }
    .header { max-width: 700px; margin: 0 auto 24px;
              display: flex; align-items: center; justify-content: space-between; }
    h1 { font-size: 1.5rem; color: #1a1a2e; }
    .count { background: #5b5ef4; color: white; border-radius: 20px;
             padding: 4px 12px; font-size: .8rem; font-weight: 600; }
    .card { background: white; border-radius: 14px; padding: 18px 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,.06); max-width: 700px;
            margin: 0 auto 12px; display: flex; align-items: flex-start; gap: 14px; }
    .card.done { opacity: .5; }
    .check { width: 22px; height: 22px; border-radius: 50%; border: 2px solid #5b5ef4;
             background: transparent; cursor: pointer; flex-shrink: 0; margin-top: 2px;
             display: flex; align-items: center; justify-content: center; }
    .check.done { background: #5b5ef4; }
    .check.done::after { content: '✓'; color: white; font-size: 13px; font-weight: bold; }
    .info { flex: 1; }
    .task-text { color: #1a1a2e; font-size: .95rem; line-height: 1.5; }
    .task-text.done { text-decoration: line-through; }
    .meta { margin-top: 6px; font-size: .78rem; color: #999; display: flex; gap: 12px; }
    .due { color: #5b5ef4; font-weight: 600; }
    .del { background: none; border: none; color: #ccc; cursor: pointer;
           font-size: 1.1rem; padding: 0 4px; flex-shrink: 0; }
    .del:hover { color: #e53e3e; }
    .empty { text-align: center; color: #999; padding: 60px 20px; max-width: 700px; margin: 0 auto; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📋 Minhas Tarefas</h1>
    <span class="count">{{ tasks|length }} tarefa{{ 's' if tasks|length != 1 else '' }}</span>
  </div>
  {% if not tasks %}
    <div class="empty">Nenhuma tarefa ainda.<br>Mande um áudio pro bot no Telegram! 🎙️</div>
  {% endif %}
  {% for t in tasks %}
  <div class="card {{ 'done' if t[4] else '' }}">
    <form method="POST" action="/toggle/{{ t[0] }}">
      <button type="submit" class="check {{ 'done' if t[4] else '' }}"></button>
    </form>
    <div class="info">
      <div class="task-text {{ 'done' if t[4] else '' }}">{{ t[2] }}</div>
      <div class="meta">
        <span>🕐 {{ t[1] }}</span>
        {% if t[3] %}<span class="due">📅 {{ t[3] }}</span>{% endif %}
      </div>
    </div>
    <form method="POST" action="/delete/{{ t[0] }}">
      <button type="submit" class="del" title="Deletar">✕</button>
    </form>
  </div>
  {% endfor %}
</body>
</html>"""

@flask_app.route("/", methods=["GET", "POST"])
def login():
    error = False
    if request.method == "POST":
        if request.form.get("password") == WEB_PASSWORD:
            session["auth"] = True
            return redirect("/tasks")
        error = True
    return render_template_string(LOGIN_HTML, error=error)

@flask_app.route("/tasks")
def tasks_page():
    if not session.get("auth"):
        return redirect("/")
    return render_template_string(TASKS_HTML, tasks=get_tasks())

@flask_app.route("/toggle/<int:task_id>", methods=["POST"])
def toggle(task_id):
    if not session.get("auth"):
        return redirect("/")
    toggle_done(task_id)
    return redirect("/tasks")

@flask_app.route("/delete/<int:task_id>", methods=["POST"])
def delete(task_id):
    if not session.get("auth"):
        return redirect("/")
    delete_task(task_id)
    return redirect("/tasks")

# ─── Inicialização ────────────────────────────────────────────────
def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    init_db()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    bot_app.run_polling(drop_pending_updates=True)
