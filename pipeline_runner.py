import os
import json
import threading
import requests
import psycopg2
from datetime import datetime

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
PIPELINE_MODEL = os.environ.get("BOT_MODEL", "google/gemini-2.0-flash-001")

# ─── Contexto da empresa ────────────────────────────────────────────────────

COMPANY_CONTEXT = """
SOBRE A BOREAL MÍDIA:
- Produtora de performance digital B2B em Itajubá-MG
- Atende PMEs: tecnologia, engenharia, energia, educação, pesquisa e inovação
- Clientes: UNIFEI, Inatel, CEMIG, GIZ, Energisa e outros de renome nacional
- Posicionamento: "a agência que entrega resultado sem romantismo para empresas B2B"
- Tom de voz: profissional, direto, sem clichês, focado em resultado mensurável
- NUNCA usar: segredo, fórmula, viralizar, crescer seguidores, branding sem objetivo
"""

# ─── System prompts dos agentes ─────────────────────────────────────────────

PEDRO_PROMPT = """Você é Pedro Pesquisa, pesquisador da Agência de Conteúdo Boreal.
Missão: transformar uma pauta em contexto estratégico com dados e insights B2B.

Princípios:
- Dados > Opinião — números, pesquisas, benchmarks sempre que possível
- Relevância B2B — filtrado pela lente de quem toma decisão em PME
- 3 achados sólidos valem mais que 10 superficiais
- Se não tiver dado exato, sinalize claramente

Entregue EXATAMENTE neste formato:
PESQUISA: [título da pauta]

CONTEXTO:
[2-3 parágrafos — por que é relevante agora, o que o mercado faz]

DADOS RELEVANTES:
1. [dado/estatística + fonte estimada]
2. [dado/estatística + fonte estimada]
3. [dado/estatística + fonte estimada]

CRENÇAS POPULARES (para ângulo contrário):
- [crença comum que pode ser desafiada]
- [crença comum que pode ser desafiada]

OPORTUNIDADE DE CONTEÚDO:
[por que esse tema funciona para a Boreal Mídia agora]
""" + COMPANY_CONTEXT

IVAN_PROMPT = """Você é Ivan Ideia, estrategista criativo da Agência de Conteúdo Boreal.
Transforma pesquisa em ângulos de conteúdo que fazem o gestor B2B parar o scroll.

Os 5 Ângulos disponíveis:
🔴 Medo/Risco | 🟢 Oportunidade | 📚 Educacional | ↔️ Contrário | ⭐ Inspiracional

Gere EXATAMENTE 3 ângulos no formato abaixo. Numere claramente como ÂNGULO 1, ÂNGULO 2, ÂNGULO 3:

ÂNGULO 1: [nome] [emoji]
JUSTIFICATIVA: [por que funciona para essa pauta]
HOOK LINKEDIN (2-3 linhas de abertura):
[hook]
HOOK INSTAGRAM:
Título: [até 8 palavras]
Subtítulo: [até 12 palavras]
TESE CENTRAL: [1 frase — o argumento que todo conteúdo vai defender]

---

ÂNGULO 2: [nome] [emoji]
[mesmo formato]

---

ÂNGULO 3: [nome] [emoji]
[mesmo formato]

Anti-padrões: sem motivacional sem dados, sem superlativos sem prova, sem palavras vetadas.
""" + COMPANY_CONTEXT

ISABELA_PROMPT = """Você é Isabela Instagram, especialista em conteúdo visual da Agência Boreal.
Domina carrosséis que educam e Reels que prendem para público B2B.

CARROSSEL (6-8 slides):
- Slide 1 (Cover): título até 8 palavras + subtítulo que promete (nunca comece com "Como")
- Slides 2-6: 1 insight por slide, headline + 2-3 linhas. Máx 25 palavras por slide
- Slide final: CTA direto e específico (não "siga para mais conteúdo")

Cores Boreal: dark (#1a1a1a) ou light (#f5f5f0), accent laranja (#E8630A)

CAPTION (obrigatório após o carrossel):
1. Linha de abertura (hook em outras palavras, máx 2 linhas)
2. Contexto/agitação (2-3 linhas)
3. Teaser ("No carrossel você vai ver...")
4. CTA ("Comenta aqui", "Salva esse post")
5. 5-8 hashtags B2B relevantes

REEL (15-30 segundos):
- 0-2s (Hook): texto na tela + fala direta — tensão imediata
- 2-8s (Setup): contexto do problema
- 8-22s (Delivery): argumento com cortes rápidos (máx 3 pontos)
- 22-30s (CTA): conclusão + ação

Anti-padrões: slide 1 sem tensão, mais de 1 ponto por slide, caption que só resume, CTA genérico.
""" + COMPANY_CONTEXT

LUCAS_PROMPT = """Você é Lucas LinkedIn, especialista em posts B2B da Agência Boreal.
Cria posts que constroem autoridade e geram leads qualificados para PMEs.

ESTRUTURA DO POST (400-600 palavras):

Abertura — Hook (2-3 linhas):
- Afirmação provocativa OU dado surpreendente OU pergunta retórica
- Deve gerar tensão para clicar "ver mais"
- NUNCA comece com "Hoje quero falar sobre..."

Desenvolvimento (Body):
- Estabelecer problema/contexto (2-3 parágrafos curtos)
- Evidências com dados ou caso real
- Análise e perspectiva Boreal
- Implicação prática

Fechamento:
- Conclusão que reforça a tese
- Pergunta aberta para comentários OU ação específica
- NUNCA pedir curtida/compartilhamento diretamente

Hashtags: 4-6 hashtags ao final

Formatação: parágrafos de máx 3 linhas, espaçamento generoso, máx 3 emojis.

Anti-padrões: abertura passiva, blocos de texto densos, mais de 2 argumentos, dados sem fonte.
""" + COMPANY_CONTEXT

YAGO_PROMPT = """Você é Yago YouTube, roteirista da Agência Boreal.
Transforma análises complexas em vídeos que gestores B2B assistem do início ao fim.

ESTRUTURA DO ROTEIRO (8-12 minutos estimados):

[TÍTULO SEO-FRIENDLY]
[Descrição do vídeo — 150 palavras com palavras-chave B2B]

ROTEIRO:

INTRO (0-60s):
[CORTE] Hook: dado surpreendente ou problema reconhecível (1-2 frases)
[TELA] Promessa: o que o espectador vai saber ao final
Credencial rápida: por que a Boreal pode falar sobre isso

CONTEXTO (60s-3min):
[desenvolver o problema com dados]
[por que importa para PMEs B2B]
[o que o mercado faz errado]

DESENVOLVIMENTO — Ponto 1, 2, 3 (3min-10min):
[cada ponto com: conceito + dado + exemplo B2B concreto]
[usar [CORTE], [TELA], [B-ROLL], [PAUSA] para produção]

CONCLUSÃO (10min-12min):
[síntese dos 3 pontos mais importantes]
[implicação prática — o que fazer agora]
[CTA justificado]

[TIMESTAMPS]
[TAGS DO VÍDEO]

Anti-padrões: intro longa, frases que soam mal faladas, mais de 5 pontos, exemplos genéricos.
""" + COMPANY_CONTEXT

# ─── Database ────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)

def ensure_pipeline_table():
    """Cria a tabela pipeline_runs se não existir."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id SERIAL PRIMARY KEY,
                run_id TEXT UNIQUE NOT NULL,
                chat_id BIGINT NOT NULL,
                current_step TEXT,
                status TEXT DEFAULT 'running',
                state_data JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_chat_status ON pipeline_runs(chat_id, status);
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Pipeline] Erro ao criar tabela: {e}")

def save_pipeline_state(run_id, chat_id, step, status, state_data):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_runs (run_id, chat_id, current_step, status, state_data, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (run_id) DO UPDATE SET
                current_step = EXCLUDED.current_step,
                status = EXCLUDED.status,
                state_data = EXCLUDED.state_data,
                updated_at = NOW()
        """, (run_id, chat_id, step, status, json.dumps(state_data, ensure_ascii=False)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Pipeline] Erro ao salvar estado: {e}")

def get_active_pipeline(chat_id):
    """Retorna pipeline aguardando input do usuário, se houver."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT run_id, current_step, status, state_data
            FROM pipeline_runs
            WHERE chat_id = %s AND status = 'waiting_input'
            ORDER BY updated_at DESC LIMIT 1
        """, (chat_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "run_id": row[0],
                "current_step": row[1],
                "status": row[2],
                "state_data": row[3] if isinstance(row[3], dict) else json.loads(row[3])
            }
        return None
    except Exception as e:
        print(f"[Pipeline] Erro ao buscar pipeline ativo: {e}")
        return None

# ─── OpenRouter ──────────────────────────────────────────────────────────────

def call_llm(system_prompt, user_content, max_tokens=2000):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": PIPELINE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        },
        timeout=90
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ─── Telegram ────────────────────────────────────────────────────────────────

def send_message(chat_id, text):
    # Telegram tem limite de 4096 chars por mensagem
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=10
            )
        except Exception as e:
            print(f"[Pipeline] Erro ao enviar mensagem: {e}")

# ─── Pipeline Steps ──────────────────────────────────────────────────────────

def step_pesquisa(pauta_text):
    return call_llm(PEDRO_PROMPT, f"Pesquise sobre esta pauta:\n\n{pauta_text}", max_tokens=1500)

def step_angulos(pauta_text, research):
    return call_llm(
        IVAN_PROMPT,
        f"Pauta: {pauta_text}\n\nPesquisa do Pedro:\n{research}\n\nGere 3 ângulos com hooks.",
        max_tokens=2000
    )

def step_instagram(pauta_text, angle_text):
    return call_llm(
        ISABELA_PROMPT,
        f"Pauta: {pauta_text}\n\nÂngulo escolhido:\n{angle_text}\n\nCrie o carrossel completo e o roteiro do Reel.",
        max_tokens=2000
    )

def step_linkedin(pauta_text, angle_text):
    return call_llm(
        LUCAS_PROMPT,
        f"Pauta: {pauta_text}\n\nÂngulo escolhido:\n{angle_text}\n\nCrie o post completo para LinkedIn.",
        max_tokens=1500
    )

def step_youtube(pauta_text, angle_text):
    return call_llm(
        YAGO_PROMPT,
        f"Pauta: {pauta_text}\n\nÂngulo escolhido:\n{angle_text}\n\nCrie o roteiro do vídeo YouTube.",
        max_tokens=2500
    )

# ─── Pipeline Main ───────────────────────────────────────────────────────────

def start_pipeline(chat_id, pauta_data):
    """Inicia o pipeline: Pedro (pesquisa) + Ivan (ângulos) → checkpoint."""
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    pauta_text = pauta_data.get("text", "")

    send_message(chat_id,
        f"🚀 Pipeline iniciado!\n\n"
        f"Pauta: {pauta_text}\n\n"
        f"🔍 Pedro está pesquisando..."
    )

    try:
        # Step 1: Pesquisa
        research = step_pesquisa(pauta_text)
        send_message(chat_id, f"✅ Pedro concluiu:\n\n{research}")

        send_message(chat_id, "💡 Ivan está gerando os ângulos...")

        # Step 2: Ângulos
        angles = step_angulos(pauta_text, research)
        send_message(chat_id,
            f"✅ Ivan gerou 3 ângulos:\n\n{angles}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👆 Qual ângulo você quer usar?\n"
            f"Responda: 1, 2 ou 3 (ou descreva qual prefere)"
        )

        # Salva estado e aguarda input
        save_pipeline_state(run_id, chat_id, "angle-checkpoint", "waiting_input", {
            "pauta_text": pauta_text,
            "pauta_data": pauta_data,
            "formatos": pauta_data.get("formatos", ["linkedin", "instagram", "youtube"]),
            "research": research,
            "angles": angles
        })

    except Exception as e:
        send_message(chat_id, f"⚠️ Erro no pipeline (etapa pesquisa): {str(e)}")
        print(f"[Pipeline] Erro: {e}")


def resume_pipeline(chat_id, pipeline_state, user_input):
    """Retoma o pipeline após input do usuário em um checkpoint."""
    state = pipeline_state["state_data"]
    current_step = pipeline_state["current_step"]
    run_id = pipeline_state["run_id"]

    if current_step == "angle-checkpoint":
        pauta_text = state["pauta_text"]
        angles = state["angles"]
        angle_context = f"Ângulo escolhido pelo Rapha: {user_input}\n\nÂngulos gerados pelo Ivan:\n{angles}"

        save_pipeline_state(run_id, chat_id, "content-creation", "running", state)
        send_message(chat_id,
            f"✅ Ângulo confirmado: {user_input}\n\n"
            f"📸 Isabela, 💼 Lucas e 🎬 Yago estão criando o conteúdo...\n"
            f"(Isso pode levar 1-2 minutos)"
        )

        try:
            formatos = state.get("formatos", ["linkedin", "instagram", "youtube"])

            # Content creation — só roda os agentes dos formatos selecionados
            if "instagram" in formatos:
                send_message(chat_id, "📸 Isabela criando Instagram...")
                instagram = step_instagram(pauta_text, angle_context)
                send_message(chat_id, f"📸 INSTAGRAM — Isabela:\n\n{instagram}")

            if "linkedin" in formatos:
                send_message(chat_id, "💼 Lucas criando LinkedIn...")
                linkedin = step_linkedin(pauta_text, angle_context)
                send_message(chat_id, f"💼 LINKEDIN — Lucas:\n\n{linkedin}")

            if "youtube" in formatos:
                send_message(chat_id, "🎬 Yago criando roteiro YouTube...")
                youtube = step_youtube(pauta_text, angle_context)
                send_message(chat_id, f"🎬 YOUTUBE — Yago:\n\n{youtube}")

            send_message(chat_id,
                "✅ Pipeline concluído!\n\n"
                "Todo o conteúdo está acima. Revise e ajuste conforme necessário.\n\n"
                "Manda uma nova ideia quando quiser rodar de novo!"
            )

            save_pipeline_state(run_id, chat_id, "completed", "completed", state)

        except Exception as e:
            send_message(chat_id, f"⚠️ Erro na criação de conteúdo: {str(e)}")
            save_pipeline_state(run_id, chat_id, "content-creation", "failed", state)


def parse_pauta(text):
    """Extrai dados estruturados do bloco PAUTA CONFIRMADA."""
    import re
    pauta = {"text": text, "raw": text, "formatos": ["linkedin", "instagram", "youtube"]}
    idea_match = re.search(r"-\s*Ideia:\s*(.+)", text)
    angle_match = re.search(r"-\s*[AÂ]ngulo:\s*(.+)", text)
    pilar_match = re.search(r"-\s*Pilar:\s*(.+)", text)
    urgency_match = re.search(r"-\s*Urg[eê]ncia:\s*(.+)", text)
    formatos_match = re.search(r"-\s*Formatos:\s*(.+)", text, re.IGNORECASE)
    notes_match = re.search(r"-\s*Notas.*?:\s*(.+)", text)
    if idea_match:
        pauta["text"] = idea_match.group(1).strip()
    if angle_match:
        pauta["angle"] = angle_match.group(1).strip()
    if pilar_match:
        pauta["pilar"] = pilar_match.group(1).strip()
    if urgency_match:
        pauta["urgency"] = urgency_match.group(1).strip()
    if notes_match:
        pauta["notes"] = notes_match.group(1).strip()
    if formatos_match:
        raw_formatos = formatos_match.group(1).strip().lower()
        if "todos" in raw_formatos:
            pauta["formatos"] = ["linkedin", "instagram", "youtube"]
        else:
            pauta["formatos"] = [f for f in ["linkedin", "instagram", "youtube"] if f in raw_formatos]
        if not pauta["formatos"]:
            pauta["formatos"] = ["linkedin", "instagram", "youtube"]
    return pauta


def trigger_pipeline(chat_id, pauta_data):
    """Chamado pelo bot.py quando uma pauta é confirmada."""
    ensure_pipeline_table()
    thread = threading.Thread(target=_run_safe, args=(chat_id, pauta_data))
    thread.daemon = True
    thread.start()


def _run_safe(chat_id, pauta_data):
    try:
        start_pipeline(chat_id, pauta_data)
    except Exception as e:
        send_message(chat_id, f"⚠️ Erro inesperado no pipeline: {str(e)}")
        print(f"[Pipeline] Erro crítico: {e}")
