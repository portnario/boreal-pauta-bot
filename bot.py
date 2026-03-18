import os
import requests
from flask import Flask, request as flask_request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
BOT_MODEL = os.environ.get("BOT_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

# Histórico de conversa por chat (em memória)
conversations = {}

SYSTEM_PROMPT = """Você é o assistente de pauta da Boreal Mídia, conversando diretamente com Raphael Ladeira (Rapha), dono da empresa.

SOBRE A BOREAL MÍDIA:
- Produtora de performance digital B2B em Itajubá-MG
- Atende PMEs nos setores de tecnologia, engenharia, energia, educação e pesquisa
- Diferencial: audiovisual de alto impacto + estratégia orientada a resultado de negócio
- Posicionamento: "a agência que entrega resultado sem romantismo para empresas B2B"

SEU PAPEL:
Você ajuda o Rapha a transformar ideias soltas em pautas de conteúdo estruturadas para Instagram, LinkedIn e YouTube.

QUANDO RAPHA MANDAR UMA IDEIA:
1. Identifique o potencial da pauta
2. Sugira 1-2 ângulos (escolha entre: Medo/Risco, Oportunidade, Educacional, Contrário, Inspiracional)
3. Faça UMA pergunta para enriquecer a pauta (dados, contexto, case real)
4. Seja direto — respostas curtas, sem enrolação

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


def call_openrouter(messages):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": BOT_MODEL,
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.7,
        },
        timeout=30
    )
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

    if not text:
        if "voice" in message or "audio" in message:
            send_message(chat_id, "Recebi seu áudio! Por enquanto só processo texto. Manda a ideia por escrito e eu ajudo a estruturar.")
        return "ok"

    # Inicializar histórico
    if chat_id not in conversations:
        conversations[chat_id] = []

    conversations[chat_id].append({"role": "user", "content": text})

    # Manter apenas as últimas 10 mensagens
    if len(conversations[chat_id]) > 10:
        conversations[chat_id] = conversations[chat_id][-10:]

    try:
        reply = call_openrouter(
            [{"role": "system", "content": SYSTEM_PROMPT}] + conversations[chat_id]
        )
        conversations[chat_id].append({"role": "assistant", "content": reply})
        send_message(chat_id, reply)
    except Exception as e:
        send_message(chat_id, f"Erro ao processar: {str(e)}")

    return "ok"


@app.route("/", methods=["GET"])
def index():
    return "Bot Boreal Midia rodando"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
