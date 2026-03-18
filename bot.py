import os
import requests
import psycopg2
import base64
from flask import Flask, request as flask_request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_MODEL = os.environ.get("BOT_MODEL", "google/gemini-2.0-flash-001")

# Histórico de conversa por chat (em memória)
conversations = {}

SYSTEM_PROMPT = """Você é o assistente de pauta da Boreal Mídia, conversando diretamente com Raphael Ladeira (Rapha), dono da empresa.

SOBRE A BOREAL MÍDIA:
- Produtora de performance digital B2B em Itajubá-MG
- Diferencial: audiovisual de alto impacto + estratégia orientada a resultado de negócio
- Posicionamento: "a agência que entrega resultado sem romantismo para empresas B2B"

SEU PAPEL:
Você ajuda o Rapha a transformar ideias soltas em pautas de conteúdo estruturadas para Instagram, LinkedIn e YouTube.

QUANDO RAPHA MANDAR UMA IDEIA (TEXTO OU ÁUDIO):
1. Identifique o potencial da pauta e mostre empolgação pragmática.
2. Sugira 1-2 ângulos (escolha entre: Medo/Risco, Oportunidade, Educacional, Contrário, Inspiracional)
3. Faça UMA pergunta para enriquecer a pauta (dados, contexto, case real)
4. Seja direto — respostas curtas, sem enrolação.

QUANDO RAPHA CONFIRMAR UMA PAUTA:
Envie uma mensagem formatada assim (exatamente):

PAUTA CONFIRMADA
- Ideia: [descrição]
- Ângulo: [nome do ângulo]
- Pilar: [Resultado Real | Bastidores | Educação | Mercado B2B | Tendências]
- Urgência: [alta | média | baixa]
- Notas: [contexto adicional se houver]

REGRAS DE COMUNICAÇÃO:
- Respostas curtas (máx 4 parágrafos curtos no Telegram)
- Tom direto, sem romantismo, sem enrolação
- Nunca use: segredo, fórmula, viralizar, crescer seguidores
- Se a ideia for fraca, diga com clareza e proponha reformulação
- Foque sempre em resultado B2B mensurável"""

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

def save_to_db(text, msg_id):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pautas (telegram_id, message_text, message_type) VALUES (%s, %s, %s) ON CONFLICT (telegram_id) DO NOTHING",
            (msg_id, text, "text")
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Erro no banco: {e}")
        return False

def get_telegram_file_path(file_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(url).json()
    if resp.get("ok"):
        return resp["result"]["file_path"]
    return None

def download_and_encode_audio(file_path):
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    resp = requests.get(url)
    if resp.status_code == 200:
        return base64.b64encode(resp.content).decode("utf-8")
    return None

def call_openrouter(messages, audio_base64=None):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://railway.app",
        "X-Title": "Boreal Pauta Bot",
    }
    
    # Se houver áudio, transformamos a última mensagem em multimodal
    if audio_base64 and messages[-1]["role"] == "user":
        last_text = messages[-1]["content"]
        messages[-1]["content"] = [
            {"type": "text", "text": last_text if last_text else "Transcreva e analise este áudio conforme seu papel."},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": audio_base64,
                    "format": "ogg" # Telegram voice é sempre ogg/opus
                }
            }
        ]
    
    payload = {
        "model": BOT_MODEL,
        "messages": messages,
        "max_tokens": 1000,
        "temperature": 0.7,
    }
    
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60 # Aumentado para processamento de áudio
    )
    
    if response.status_code != 200:
        print(f"OPENROUTER ERROR: {response.status_code} - {response.text}")
        
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

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
    text = message.get("text", "")
    msg_id = message["message_id"]
    audio_b64 = None

    # Tratar áudio/voz
    if not text and "voice" in message:
        file_id = message["voice"]["file_id"]
        file_path = get_telegram_file_path(file_id)
        if file_path:
            audio_b64 = download_and_encode_audio(file_path)
            # Para o histórico, o texto do áudio será marcado como vazio para ser preenchido pela transcrição
            text = "[Mensagem de Voz]"

    if not text and not audio_b64:
        return "ok"

    if chat_id not in conversations:
        conversations[chat_id] = []

    conversations[chat_id].append({"role": "user", "content": text})

    if len(conversations[chat_id]) > 10:
        conversations[chat_id] = conversations[chat_id][-10:]

    try:
        reply = call_openrouter(
            [{"role": "system", "content": SYSTEM_PROMPT}] + conversations[chat_id],
            audio_base64=audio_b64
        )
        
        if "PAUTA CONFIRMADA" in reply:
            save_to_db(reply, msg_id)
            reply += "\n\n🚀 **Enviado para o Squad Boreal!**"

        conversations[chat_id].append({"role": "assistant", "content": reply})
        send_message(chat_id, reply)
    except Exception as e:
        print(f"ERRO WEBHOOK: {e}")
        send_message(chat_id, f"Erro ao processar: {str(e)}")

    return "ok"

@app.route("/", methods=["GET"])
def index():
    return f"Bot Boreal Mídia (Tiago) com Audição Ativa em {BOT_MODEL}."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
