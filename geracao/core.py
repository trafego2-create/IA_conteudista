import hashlib
import itertools
import json
import os
import re
from datetime import datetime, timezone

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
3. Se um EXEMPLO DE REFERÊNCIA for fornecido, use-o só para calibrar tom,
   profundidade e estrutura do comentário (é uma questão real de banca, revisada
   por humano). Nunca copie seu conteúdo nem cite a lei mencionada nele - a
   única fonte válida de citação continua sendo o TRECHO.
4. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

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
{exemplo_calibracao}
Gere 1 questão comentada no formato certo_errado sobre este trecho."""

BLOCO_EXEMPLO_CALIBRACAO = """
EXEMPLO DE REFERÊNCIA (questão real de banca, só para calibrar tom/estilo - não copiar):
Enunciado: {enunciado}
Gabarito: {gabarito}
Comentário: {comentario}
"""

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


class EstoqueInsuficiente(Exception):
    pass


class QuestaoNaoEncontrada(Exception):
    pass


class DecisaoInvalida(Exception):
    pass


def get_supabase():
    return create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])


def get_openai():
    return OpenAI(api_key=os.environ['OPENAI_API_KEY'])


def buscar_exemplo_calibracao(supabase, concurso: str, materia: str, formato: str) -> str:
    """Busca 1 questao real (origem='banco_real', ja revisada por humano no curso de
    origem) da mesma materia/formato pra calibrar tom e profundidade do comentario
    gerado pela IA. Best-effort: se nao achar nenhuma, retorna bloco vazio - a
    geracao segue normalmente sem calibracao, so com o TRECHO como fonte."""
    if not formato:
        return ''
    consulta = (
        supabase.table('questoes')
        .select('enunciado, gabarito, comentario')
        .eq('origem', 'banco_real')
        .eq('materia', materia)
        .eq('formato', formato)
    )
    if concurso:
        consulta = consulta.eq('concurso', concurso)
    resultado = consulta.limit(1).execute()
    if not resultado.data:
        return ''
    exemplo = resultado.data[0]
    return BLOCO_EXEMPLO_CALIBRACAO.format(**exemplo)


def gerar_questao(
    materia: str, tema: str, produto: str = 'mestre_questoes', model: str = 'gpt-4.1',
    concurso: str = None,
) -> dict:
    if produto not in PRODUTOS:
        raise ProdutoInvalido(f'produto deve ser um de {list(PRODUTOS)}, recebido {produto!r}')
    config = PRODUTOS[produto]

    supabase = get_supabase()
    openai_client = get_openai()

    consulta_fonte = supabase.table('material_fonte').select('*').eq('materia', materia).eq('tema', tema)
    if concurso:
        consulta_fonte = consulta_fonte.eq('concurso', concurso)
    fonte = consulta_fonte.limit(1).execute()
    if not fonte.data:
        raise MaterialNaoEncontrado(f'nenhum material_fonte para materia={materia!r} tema={tema!r}')
    registro = fonte.data[0]
    trecho = registro['trecho']

    exemplo_calibracao = buscar_exemplo_calibracao(supabase, registro['concurso'], registro['materia'], config['formato'])

    user_prompt = config['user_prompt'].format(
        concurso=registro['concurso'], materia=registro['materia'],
        tema=registro['tema'], trecho=trecho, exemplo_calibracao=exemplo_calibracao,
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


def listar_temas(concurso: str) -> list[tuple]:
    supabase = get_supabase()
    resultado = (
        supabase.table('material_fonte')
        .select('materia, tema, ordem')
        .eq('concurso', concurso)
        .order('materia')
        .order('ordem')
        .execute()
    )
    if not resultado.data:
        raise MaterialNaoEncontrado(f'nenhum material_fonte para concurso={concurso!r}')

    vistos = set()
    temas = []
    for linha in resultado.data:
        chave = (linha['materia'], linha['tema'])
        if chave not in vistos:
            vistos.add(chave)
            temas.append(chave)
    return temas


def gerar_lote(concurso: str, quantidade: int, produto: str = 'mestre_questoes', model: str = 'gpt-4.1') -> dict:
    """Gera `quantidade` questoes novas via IA, uma por tema em round-robin. Nunca reaproveita -
    Mestre em Questoes e sempre 100% gerado. Falhas pontuais (ex.: duplicata de hash) nao derrubam
    o lote inteiro, ficam listadas em 'falhas'."""
    temas = listar_temas(concurso)

    resultados = []
    falhas = []
    for materia, tema in itertools.islice(itertools.cycle(temas), quantidade):
        try:
            resultados.append(gerar_questao(materia, tema, produto, model, concurso=concurso))
        except Exception as e:
            falhas.append({'materia': materia, 'tema': tema, 'erro': str(e)})

    return {
        'concurso': concurso,
        'produto': produto,
        'solicitado': quantidade,
        'gerado_com_sucesso': len(resultados),
        'pendente_revisao': sum(1 for r in resultados if r['status'] == 'pendente_revisao'),
        'rejeitada': sum(1 for r in resultados if r['status'] == 'rejeitada'),
        'falhas': falhas,
        'questoes': resultados,
    }


DECISOES_VALIDAS = ('aprovada', 'rejeitada')


def revisar_questao(questao_id: int, decisao: str, revisado_por: str = None, motivo_rejeicao: str = None) -> dict:
    """Aplica a decisao de revisao humana numa questao pendente (ou ja revisada -
    pode-se corrigir uma decisao anterior). Nenhuma questao vira 'aprovada' por
    nenhum outro caminho que nao seja este, conforme regra de negocio do briefing."""
    if decisao not in DECISOES_VALIDAS:
        raise DecisaoInvalida(f'decisao deve ser uma de {DECISOES_VALIDAS}, recebido {decisao!r}')

    supabase = get_supabase()
    atualizacao = {
        'status': decisao,
        'revisado_por': revisado_por,
        'revisado_em': datetime.now(timezone.utc).isoformat(),
        'motivo_rejeicao': motivo_rejeicao if decisao == 'rejeitada' else None,
    }
    resultado = supabase.table('questoes').update(atualizacao).eq('id', questao_id).execute()
    if not resultado.data:
        raise QuestaoNaoEncontrada(f'nenhuma questao com id={questao_id!r}')
    return resultado.data[0]


def _prioridade_reuso(questao: dict):
    usos = questao.get('usada_em') or []
    return (len(usos), max(usos) if usos else '')


def _candidatas_aprovadas(supabase, concurso: str, materia: str = None, formato: str = None) -> list:
    consulta = supabase.table('questoes').select('*').eq('concurso', concurso).eq('status', 'aprovada')
    if materia:
        # ilike sem coringa = igualdade ignorando maiuscula/minuscula - o nome da materia
        # digitado em linguagem natural (ex.: "direito constitucional") raramente bate
        # exatamente a grafia salva no banco (ex.: "Direito Constitucional")
        consulta = consulta.ilike('materia', materia)
    if formato:
        consulta = consulta.eq('formato', formato)
    candidatas = consulta.execute().data
    candidatas.sort(key=_prioridade_reuso)
    return candidatas


def listar_materias(concurso: str) -> list:
    """Nomes de materia distintos com estoque aprovado para o concurso, na grafia exata
    salva no banco - usado pelo assistente pra alinhar a distribuicao por materia de um
    simulado antes de chamar sortear_simulado_estratificado (nomes tipo 'RLM' nao sao
    obvios a partir do pedido em linguagem natural do usuario)."""
    supabase = get_supabase()
    resultado = (
        supabase.table('questoes')
        .select('materia')
        .eq('concurso', concurso)
        .eq('status', 'aprovada')
        .execute()
    )
    return sorted({linha['materia'] for linha in resultado.data})


def _marcar_usadas(supabase, selecionadas: list) -> None:
    agora = datetime.now(timezone.utc).isoformat()
    for questao in selecionadas:
        novo_usada_em = (questao.get('usada_em') or []) + [agora]
        supabase.table('questoes').update({'usada_em': novo_usada_em}).eq('id', questao['id']).execute()


def sortear_simulado(concurso: str, quantidade: int, formato: str = None) -> dict:
    """Monta um simulado sorteando questoes JA aprovadas do banco. Sem IA - se nao houver
    estoque aprovado suficiente, falha (nao existe fallback gerando questoes novas para
    simulado, e regra de negocio). Prioriza questoes nunca usadas ou usadas ha mais tempo.
    formato (opcional) restringe a 'certo_errado' ou 'abcde' - sem isso o sorteio mistura os
    dois formatos aprovados pra mesma materia, o que nao e o que o usuario pede na pratica
    quando fala em "modelo Certo/Errado" ou "multipla escolha"."""
    supabase = get_supabase()

    candidatas = _candidatas_aprovadas(supabase, concurso, formato=formato)
    if len(candidatas) < quantidade:
        raise EstoqueInsuficiente(
            f'apenas {len(candidatas)} questoes aprovadas para concurso={concurso!r} '
            f'formato={formato!r} (pedido de {quantidade}) - simulado nunca usa IA, so '
            f'reaproveitamento do banco'
        )

    selecionadas = candidatas[:quantidade]
    _marcar_usadas(supabase, selecionadas)

    return {
        'concurso': concurso,
        'quantidade': len(selecionadas),
        'questoes': selecionadas,
    }


def sortear_simulado_estratificado(concurso: str, distribuicao: dict, formato: str = None) -> dict:
    """Igual sortear_simulado, mas com quantidade fixa por materia (ex.: {'Português': 3,
    'Redação Oficial': 1, ...}), pra atender pedidos de simulado com proporcao definida por
    materia em vez de so um total solto. Confere o estoque de TODAS as materias pedidas antes
    de marcar qualquer questao como usada - ou monta o simulado inteiro, ou nao mexe em nada
    (evita gastar estoque de materias que tinham saldo enquanto outra materia falha). formato
    (opcional) restringe a 'certo_errado' ou 'abcde', aplicado igual em todas as materias."""
    supabase = get_supabase()

    candidatas_por_materia = {}
    faltando = []
    for materia, quantidade in distribuicao.items():
        candidatas = _candidatas_aprovadas(supabase, concurso, materia, formato=formato)
        if len(candidatas) < quantidade:
            faltando.append({'materia': materia, 'pedido': quantidade, 'disponivel': len(candidatas)})
        candidatas_por_materia[materia] = candidatas

    if faltando:
        detalhe = '; '.join(f"{f['materia']}: pedido {f['pedido']}, disponivel {f['disponivel']}" for f in faltando)
        raise EstoqueInsuficiente(
            f'estoque aprovado insuficiente para concurso={concurso!r} formato={formato!r} '
            f'nas materias: {detalhe} - simulado nunca usa IA, so reaproveitamento do banco'
        )

    selecionadas = []
    for materia, quantidade in distribuicao.items():
        selecionadas.extend(candidatas_por_materia[materia][:quantidade])

    _marcar_usadas(supabase, selecionadas)

    return {
        'concurso': concurso,
        'distribuicao': distribuicao,
        'quantidade': len(selecionadas),
        'questoes': selecionadas,
    }
