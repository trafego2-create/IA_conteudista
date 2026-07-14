import hashlib
import json
import os
import re

from openai import OpenAI
from supabase import create_client

SYSTEM_PROMPT_MESTRE_QUESTOES = """Você é um conteudista especializado em concursos públicos, escrevendo questões
comentadas no padrão da plataforma Aprova Sim, com o mesmo nível de profundidade
jurídica e didática do material de referência.

REGRAS OBRIGATÓRIAS:
1. Use apenas o TRECHO fornecido como fonte de conteúdo. Nunca cite lei, decreto,
   artigo ou instrução normativa que não apareça literalmente no TRECHO.
2. Qualquer citação legal no campo "comentario" deve ser uma transcrição literal
   de um trecho do TRECHO fornecido, delimitada entre aspas retas (" ").
   Não parafraseie o texto legal citado.
3. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

FORMATO DE SAÍDA (JSON):
{
  "enunciado": "...",
  "gabarito": "CERTO" ou "ERRADO",
  "comentario": "..."
}"""

USER_PROMPT_MESTRE_QUESTOES = """CONCURSO: {concurso}
MATÉRIA: {materia}
TEMA: {tema}
FORMATO: certo_errado

TRECHO (fonte de verdade, não usar nada fora daqui):
\"\"\"
{trecho}
\"\"\"

Gere 1 questão comentada no formato certo_errado sobre este trecho."""

SYSTEM_PROMPT_REVISAO_FAROL = """Você é um conteudista especializado em concursos públicos, escrevendo flashcards
de revisão (Revisão Farol) para a plataforma Aprova Sim: pergunta direta de um
lado, resposta objetiva do outro, para revisão espaçada.

REGRAS OBRIGATÓRIAS:
1. Use apenas o TRECHO fornecido como fonte de conteúdo. Nunca cite lei, decreto,
   artigo ou instrução normativa que não apareça literalmente no TRECHO.
2. Se a resposta envolver citação legal, ela deve ser uma transcrição literal de
   um trecho do TRECHO fornecido, delimitada entre aspas retas (" "). Não
   parafraseie o texto legal citado.
3. A pergunta deve ter resposta objetiva e curta (não é questão certo/errado nem
   de múltipla escolha - é flashcard).
4. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

FORMATO DE SAÍDA (JSON):
{
  "enunciado": "...",
  "resposta": "..."
}"""

USER_PROMPT_REVISAO_FAROL = """CONCURSO: {concurso}
MATÉRIA: {materia}
TEMA: {tema}

TRECHO (fonte de verdade, não usar nada fora daqui):
\"\"\"
{trecho}
\"\"\"

Gere 1 flashcard (pergunta e resposta) de revisão sobre este trecho."""

PRODUTOS = {
    'mestre_questoes': {
        'system_prompt': SYSTEM_PROMPT_MESTRE_QUESTOES,
        'user_prompt': USER_PROMPT_MESTRE_QUESTOES,
        'formato': 'certo_errado',
        'exigir_citacao': True,
    },
    'revisao_farol': {
        'system_prompt': SYSTEM_PROMPT_REVISAO_FAROL,
        'user_prompt': USER_PROMPT_REVISAO_FAROL,
        'formato': None,
        'exigir_citacao': False,
    },
}


def validar_citacao(texto: str, trecho: str, exigir_citacao: bool) -> bool:
    citacoes = re.findall(r'"([^"]+)"', texto)
    if not citacoes:
        return not exigir_citacao
    trecho_norm = re.sub(r'\s+', ' ', trecho).upper()
    for citacao in citacoes:
        citacao_norm = re.sub(r'\s+', ' ', citacao).strip().upper()
        if citacao_norm not in trecho_norm:
            return False
    return True


class MaterialNaoEncontrado(Exception):
    pass


class ProdutoInvalido(Exception):
    pass


def get_supabase():
    return create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])


def get_openai():
    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])


def gerar_questao(materia: str, tema: str, produto: str = 'mestre_questoes', model: str = 'gpt-4.1') -> dict:
    if produto not in PRODUTOS:
        raise ProdutoInvalido(f'produto deve ser um de {list(PRODUTOS)}, recebido {produto!r}')
    config = PRODUTOS[produto]

    supabase = get_supabase()
    openai_client = get_openai()

    fonte = (
        supabase.table('material_fonte')
        .select('*')
        .eq('materia', materia)
        .eq('tema', tema)
        .limit(1)
        .execute()
    )
    if not fonte.data:
        raise MaterialNaoEncontrado(f'nenhum material_fonte para materia={materia!r} tema={tema!r}')
    registro = fonte.data[0]
    trecho = registro['trecho']

    user_prompt = config['user_prompt'].format(
        concurso=registro['concurso'], materia=registro['materia'],
        tema=registro['tema'], trecho=trecho,
    )

    resposta = openai_client.chat.completions.create(
        model=model,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': config['system_prompt']},
            {'role': 'user', 'content': user_prompt},
        ],
    )
    questao = json.loads(resposta.choices[0].message.content)

    texto_para_validar = questao.get('comentario') or questao.get('resposta', '')
    citacao_ok = validar_citacao(texto_para_validar, trecho, config['exigir_citacao'])
    status = 'pendente_revisao' if citacao_ok else 'rejeitada'
    motivo_rejeicao = None if citacao_ok else 'citacao legal nao encontrada literalmente no material_fonte'

    hash_conteudo = hashlib.sha256(questao['enunciado'].encode('utf-8')).hexdigest()

    insercao = {
        'concurso': registro['concurso'],
        'materia': registro['materia'],
        'tema': registro['tema'],
        'origem': produto,
        'formato': config['formato'],
        'status': status,
        'motivo_rejeicao': motivo_rejeicao,
        'enunciado': questao['enunciado'],
        'gabarito': questao.get('gabarito') or questao.get('resposta'),
        'comentario': questao.get('comentario'),
        'arquivo_origem': registro['arquivo_origem'],
        'hash_conteudo': hash_conteudo,
    }
    resultado = supabase.table('questoes').insert(insercao).execute()

    return {
        'id': resultado.data[0]['id'],
        'status': status,
        'citacao_validada': citacao_ok,
        **questao,
    }
