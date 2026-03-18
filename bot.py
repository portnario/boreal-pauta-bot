import os
import requests
import psycopg2
from flask import Flask, request as flask_request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Carrega as variáveis com fallbacks seguros
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Tenta converter o chat_id, se der erro (como 'seu_chat_id_aqui'), usa 0
raw_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "0")
try:
    TELEGRAM_CHAT_ID = int(raw_chat_id)
except ValueError:
    TELEGRAM_CHAT_ID = 0

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

def send_message(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = flask_request.json

    if "message" not in data:
        return "ok"

    message = data["message"]
    chat_id = message["chat"]["id"]
    
    # Segurança: Apenas o chat autorizado
    if TELEGRAM_CHAT_ID != 0 and chat_id != TELEGRAM_CHAT_ID:
        return "ok"

    msg_id = message["message_id"]
    text = message.get("text", "")
    msg_type = "text"

    if "voice" in message:
        msg_type = "voice"
        text = "[Áudio enviado - Aguardando processamento pelo Squad]"

    # Salva no banco de dados (PostgreSQL no Railway)
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pautas (telegram_id, message_text, message_type) VALUES (%s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING",
            (msg_id, text, msg_type)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        # Feedback imediato para o Rapha
        send_message(chat_id, "✅ Ideia capturada! O Squad Boreal já recebeu sua pauta e vai começar a processar. 🚀")
        
    except Exception as e:
        print(f"Erro ao salvar no banco: {e}")
        # Se for erro no banco, avisa no chat também
        send_message(chat_id, f"❌ Erro ao capturar pauta no banco: {str(e)}")

    return "ok"

@app.route("/", methods=["GET"])
def index():
    return "Boreal Bot Gateway is active. Ready to connect."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
