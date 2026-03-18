import os
import requests
import psycopg2
import base64
from flask import Flask, request as flask_request
from dotenv import load_dotenv
import pipeline_runner

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_MODEL = os.environ.get("BOT_MODEL", "google/gemini-2.0-flash-001")

# Histórico de conversa por chat (em memória)
conversations = {}

SYSTEM_PROMPT = """Você é a Luma, gerente de pautas e conteúdo da Boreal Mídia. Você é o ponto de contato principal do Raphael Ladeira (Rapha).

SEU TIME (SQUAD BOREAL):
Você gerencia um time de especialistas que entra em ação assim que você confirma uma pauta:
1. Pedro Pesquisa: Varre a internet atrás de dados e notícias reais para embasar a pauta.
2. Ivan Ideia: Cria ganchos criativos e ângulos de retenção.
3. Isabela Instagram: Cria roteiros de Reels e carrosséis estratégicos.
4. Lucas LinkedIn: Transforma a pauta em autoridade e posts B2B.
5. Yago YouTube: Cria roteiros estruturados para vídeos longos.
6. Vera Veredito: Faz a revisão final de tom de voz "Anti-Guru" e qualidade.

SOBRE A BOREAL MÍDIA:
- Produtora de performance digital B2B em Itajubá-MG.
- Posicionamento: "Agência que entrega resultado sem romantismo".
- Público: PMEs de tecnologia, engenharia e educação.

SEU PAPEL COM O RAPHA:
Você ajuda o Rapha a refinar ideias. Você é organizada, direta e estratégica.
- Use os pilares: Resultado Real, Bastidores, Educação, Mercado B2B ou Tendências.

QUANDO RAPHA MANDAR ÁUDIO:
1. Transcreva o áudio COMPLETAMENTE e fielmente, palavra por palavra, no bloco abaixo:

TRANSCRIÇÃO COMPLETA
[tudo que o Rapha disse, sem resumir, sem interpretar]
FIM DA TRANSCRIÇÃO

2. Depois da transcrição, dê sua análise executiva: potencial da ideia e 1-2 ângulos sugeridos.
3. Pergunte qual formato de conteúdo o Rapha quer: LinkedIn, Instagram, YouTube ou todos.

QUANDO A PAUTA ESTIVER PRONTA:
Envie EXATAMENTE este bloco para salvar no sistema e acionar o time:

PAUTA CONFIRMADA
- Ideia: [descrição]
- Gerente responsável: Luma
- Ângulo: [nome do ângulo]
- Pilar: [Nome do Pilar]
- Urgência: [alta | média | baixa]
- Formatos: [linkedin | instagram | youtube | todos]
- Notas para o Time: [ex: Pedro, foque em dados de IA; Isabela, queremos algo visual]

REGRAS:
- Respostas curtas e executivas.
- Nunca use termos de "guru" (fórmula, segredo, viralizar).
- Se a ideia for fraca, diga: "Rapha, como gerente, acho que essa pauta não traz resultado. Que tal irmos por aqui...?" """

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

def save_to_db(text, msg_id, msg_type="text"):
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
        "X-Title": "Boreal Luma Manager",
    }
    
    if audio_base64 and messages[-1]["role"] == "user":
        last_text = messages[-1]["content"]
        messages[-1]["content"] = [
            {"type": "text", "text": last_text if last_text and last_text != "[Mensagem de Voz]" else "Luma, transcreva esse áudio e me dê sua opinião de gerente estrategista."},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": audio_base64,
                    "format": "ogg"
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
        timeout=60
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

    if not text and "voice" in message:
        file_id = message["voice"]["file_id"]
        file_path = get_telegram_file_path(file_id)
        if file_path:
            audio_b64 = download_and_encode_audio(file_path)
            text = "[Mensagem de Voz]"

    if not text and not audio_b64:
        return "ok"

    # ── Verificar se há pipeline aguardando input ──────────────────────────
    if text:
        active_pipeline = pipeline_runner.get_active_pipeline(chat_id)
        if active_pipeline:
            pipeline_runner.resume_pipeline(chat_id, active_pipeline, text)
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
        
        if audio_b64 and "TRANSCRIÇÃO COMPLETA" in reply:
            save_to_db(reply, msg_id, "audio_transcricao")
        elif "PAUTA CONFIRMADA" in reply:
            save_to_db(reply, msg_id, "pauta")
            pipeline_runner.trigger_pipeline(chat_id, pipeline_runner.parse_pauta(reply))

        conversations[chat_id].append({"role": "assistant", "content": reply})
        send_message(chat_id, reply)
    except Exception as e:
        print(f"ERRO WEBHOOK: {e}")
        send_message(chat_id, f"Luma aqui, tive um pequeno problema técnico ao processar: {str(e)}")

    return "ok"

@app.route("/", methods=["GET"])
def index():
    return f"Luma (Gerente Boreal) ativa com {BOT_MODEL}."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
