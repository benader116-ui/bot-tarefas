from main import flask_app, init_db, set_webhook

init_db()
set_webhook()
app = flask_app
