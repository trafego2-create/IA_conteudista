import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import (  # noqa: E402
    PRODUTOS, DecisaoInvalida, EstoqueInsuficiente, MaterialNaoEncontrado, ProdutoInvalido,
    QuestaoNaoEncontrada, gerar_lote, gerar_questao, get_openai, revisar_questao, sortear_simulado,
)

app = FastAPI(title='Aprova Sim - IA Conteudista')

STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'static')

SYSTEM_PROMPT_CHAT = """Você é o assistente de conteúdo da Aprova Sim, conversando com o time de Produto.

Converse naturalmente (responda saudações, tire dúvidas). Quando pedirem para gerar questões
novas (Mestre em Questões ou Revisão Farol), use a ferramenta gerar_questoes. Quando pedirem
para montar/gerar um simulado, use a ferramenta montar_simulado.

Regras de negócio importantes, explique ao usuário quando relevante:
- Simulados NUNCA são gerados por IA - são sempre sorteados do banco de questões já aprovadas
  por revisão humana. Se a ferramenta falhar por falta de estoque aprovado suficiente, não existe
  fallback gerando questões novas para simulado - explique isso e sugira gerar mais questões
  Mestre em Questões primeiro (que depois de revisadas e aprovadas entram no estoque de simulados).
- Questões geradas por IA (Mestre em Questões, Revisão Farol) sempre nascem como pendentes de
  revisão humana - nenhuma vai ao aluno antes de alguém aprovar.
"""

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'gerar_questoes',
            'description': (
                'Gera N questões NOVAS via IA para um concurso, no formato Mestre em Questões '
                '(comentada, com gabarito e citação legal) ou Revisão Farol (flashcard). '
                'Cada questão nasce como pendente de revisão humana.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'concurso': {'type': 'string', 'description': 'Ex.: INSS, TJSP, BB'},
                    'quantidade': {'type': 'integer'},
                    'produto': {
                        'type': 'string',
                        'enum': ['mestre_questoes', 'revisao_farol'],
                        'default': 'mestre_questoes',
                    },
                },
                'required': ['concurso', 'quantidade'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'montar_simulado',
            'description': (
                'Monta um simulado de N questões sorteando do banco de questões JÁ aprovadas '
                'por revisão humana para o concurso. Não usa IA. Falha se não houver questões '
                'aprovadas suficientes no banco.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'concurso': {'type': 'string'},
                    'quantidade': {'type': 'integer'},
                },
                'required': ['concurso', 'quantidade'],
            },
        },
    },
]


def executar_ferramenta(nome: str, argumentos: dict) -> dict:
    if nome == 'gerar_questoes':
        try:
            return gerar_lote(
                argumentos['concurso'], argumentos['quantidade'],
                argumentos.get('produto', 'mestre_questoes'),
            )
        except (MaterialNaoEncontrado, ProdutoInvalido) as e:
            return {'erro': str(e)}
    if nome == 'montar_simulado':
        try:
            return sortear_simulado(argumentos['concurso'], argumentos['quantidade'])
        except EstoqueInsuficiente as e:
            return {'erro': str(e)}
    return {'erro': f'ferramenta desconhecida: {nome}'}


class GerarRequest(BaseModel):
    materia: str
    tema: str
    produto: str = 'mestre_questoes'
    model: str = 'gpt-4.1'


class RevisaoRequest(BaseModel):
    decisao: str  # 'aprovada' ou 'rejeitada'
    revisado_por: str | None = None
    motivo_rejeicao: str | None = None


class Mensagem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    mensagens: list[Mensagem]
    model: str = 'gpt-4.1'


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/')
def chat_ui():
    return FileResponse(os.path.join(STATIC_DIR, 'chat.html'))


@app.post('/gerar')
def gerar(req: GerarRequest):
    try:
        return gerar_questao(req.materia, req.tema, req.produto, req.model)
    except MaterialNaoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProdutoInvalido as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post('/questoes/{questao_id}/revisar')
def revisar(questao_id: int, req: RevisaoRequest):
    try:
        return revisar_questao(questao_id, req.decisao, req.revisado_por, req.motivo_rejeicao)
    except DecisaoInvalida as e:
        raise HTTPException(status_code=400, detail=str(e))
    except QuestaoNaoEncontrada as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post('/chat')
def chat(req: ChatRequest):
    client = get_openai()
    mensagens = [{'role': 'system', 'content': SYSTEM_PROMPT_CHAT}]
    mensagens += [m.model_dump() for m in req.mensagens]

    # so questoes vindas de gerar_questoes nascem pendentes de revisao - as de
    # montar_simulado ja sao 'aprovada' por definicao, nao precisam de botao
    questoes_geradas = []

    for _ in range(5):
        resposta = client.chat.completions.create(
            model=req.model,
            messages=mensagens,
            tools=TOOLS,
        )
        msg = resposta.choices[0].message

        if not msg.tool_calls:
            return {'resposta': msg.content, 'questoes_geradas': questoes_geradas}

        mensagens.append(msg.model_dump(exclude_none=True))
        for chamada in msg.tool_calls:
            argumentos = json.loads(chamada.function.arguments)
            resultado = executar_ferramenta(chamada.function.name, argumentos)
            if chamada.function.name == 'gerar_questoes':
                questoes_geradas.extend(resultado.get('questoes', []))
            mensagens.append({
                'role': 'tool',
                'tool_call_id': chamada.id,
                'content': json.dumps(resultado, ensure_ascii=False),
            })

    raise HTTPException(status_code=500, detail='limite de chamadas de ferramenta excedido numa unica resposta')
