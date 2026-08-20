import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import (  # noqa: E402
    PRODUTOS, DecisaoInvalida, EstoqueInsuficiente, MaterialNaoEncontrado, ProdutoInvalido,
    QuestaoNaoEncontrada, gerar_lote, gerar_questao, get_openai, listar_concursos, listar_materias,
    revisar_questao, sortear_simulado, sortear_simulado_estratificado,
)

app = FastAPI(title='Aprova Sim - IA Conteudista')

STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'static')

SYSTEM_PROMPT_CHAT = """Você é o assistente de conteúdo da Aprova Sim, conversando com o time de Produto.

Converse naturalmente (responda saudações, tire dúvidas). Quando pedirem para gerar questões
novas (Mestre em Questões ou Revisão Farol), use a ferramenta gerar_questoes. Quando pedirem
para montar/gerar um simulado, use a ferramenta montar_simulado.

Regras de negócio importantes, explique ao usuário quando relevante:
- O concurso é sempre identificado por uma SIGLA interna no banco (ex.: BB, INSS, TJSP, CEF,
  PETR, MPSP-OP), não pelo nome por extenso. Se o usuário mencionar o concurso por extenso ou
  de forma diferente da sigla (ex.: "Banco do Brasil", "Petrobrás", "Caixa Econômica Federal"),
  SEMPRE chame listar_concursos primeiro pra descobrir a sigla exata antes de chamar
  gerar_questoes ou montar_simulado - passar o nome por extenso direto faz a ferramenta
  responder "sem material cadastrado" mesmo quando o material existe.
- Simulados NUNCA são gerados por IA - são sempre sorteados do banco de questões já aprovadas
  por revisão humana. Se a ferramenta falhar por falta de estoque aprovado suficiente, não existe
  fallback gerando questões novas para simulado - explique isso e sugira gerar mais questões
  Mestre em Questões primeiro (que depois de revisadas e aprovadas entram no estoque de simulados).
- Se o usuário pedir um simulado com quantidade por matéria (ex.: "3 de Português, 1 de Redação..."),
  use o parâmetro distribuicao da ferramenta montar_simulado em vez do parâmetro quantidade solto.
  ANTES de montar a distribuicao, sempre chame listar_materias pra pegar a grafia exata das
  matérias daquele concurso no banco (nomes como "RLM" não são óbvios a partir do pedido do
  usuário, e maiúscula/minúscula ou variações de escrita podem não bater).
- Questões geradas por IA (Mestre em Questões, Revisão Farol) sempre nascem como pendentes de
  revisão humana - nenhuma vai ao aluno antes de alguém aprovar.

Ao listar questões (de um simulado ou recém-geradas) na resposta, siga este formato exato pra
cada questão, sem markdown/negrito e sem agrupar por matéria com cabeçalho - só numeração
sequencial "01.", "02." etc:

01. "<enunciado>"

( ) Certo
( ) Errado

Comentário: <comentario>

Gabarito: <Certo ou Errado>

Pra questões de múltipla escolha (formato abcde), troca o bloco "( ) Certo / ( ) Errado" por
uma alternativa por linha ("A) ...", "B) ...", etc) e o Gabarito é a letra correta.
"""

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'listar_concursos',
            'description': (
                'Lista as siglas de concurso (grafia exata salva no banco) que têm material '
                'cadastrado pra geração via IA. Chamar antes de gerar_questoes ou montar_simulado '
                'quando o usuário mencionar o concurso por extenso ou de forma diferente da sigla.'
            ),
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
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
            'name': 'listar_materias',
            'description': (
                'Lista os nomes de matéria (grafia exata salva no banco) que têm questões '
                'aprovadas para o concurso. Chamar antes de montar_simulado com distribuicao, '
                'pra usar os nomes certos.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'concurso': {'type': 'string'},
                },
                'required': ['concurso'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'montar_simulado',
            'description': (
                'Monta um simulado sorteando do banco de questões JÁ aprovadas por revisão '
                'humana para o concurso. Não usa IA. Falha se não houver questões aprovadas '
                'suficientes no banco (avisa exatamente onde falta estoque). Use quantidade '
                'para um total solto (sem distinção de matéria) OU distribuicao para pedir uma '
                'quantidade especifica por matéria - nunca os dois juntos.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'concurso': {'type': 'string'},
                    'quantidade': {
                        'type': 'integer',
                        'description': 'Total de questões, sem distinção de matéria. Omitir se usar distribuicao.',
                    },
                    'distribuicao': {
                        'type': 'object',
                        'additionalProperties': {'type': 'integer'},
                        'description': (
                            'Quantidade de questões por matéria, ex.: {"Português": 3, "Redação Oficial": 1}. '
                            'Usar quando o pedido especificar quantidade por matéria. Omitir se usar quantidade.'
                        ),
                    },
                    'formato': {
                        'type': 'string',
                        'enum': ['certo_errado', 'abcde'],
                        'description': (
                            'Restringe o simulado a um único formato de questão. Usar sempre que o pedido '
                            'mencionar o modelo (ex.: "Certo/Errado", "múltipla escolha") - sem isso o '
                            'sorteio mistura os dois formatos aprovados para a mesma matéria.'
                        ),
                    },
                },
                'required': ['concurso'],
            },
        },
    },
]


def executar_ferramenta(nome: str, argumentos: dict) -> dict:
    if nome == 'listar_concursos':
        return {'concursos': listar_concursos()}
    if nome == 'gerar_questoes':
        try:
            return gerar_lote(
                argumentos['concurso'], argumentos['quantidade'],
                argumentos.get('produto', 'mestre_questoes'),
            )
        except (MaterialNaoEncontrado, ProdutoInvalido) as e:
            return {'erro': str(e)}
    if nome == 'listar_materias':
        return {'materias': listar_materias(argumentos['concurso'])}
    if nome == 'montar_simulado':
        try:
            formato = argumentos.get('formato')
            if argumentos.get('distribuicao'):
                return sortear_simulado_estratificado(argumentos['concurso'], argumentos['distribuicao'], formato)
            return sortear_simulado(argumentos['concurso'], argumentos['quantidade'], formato)
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
