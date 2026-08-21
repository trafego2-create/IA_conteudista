import hashlib
import itertools
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

from openai import OpenAI
from supabase import create_client

# nome por extenso (ou variacoes comuns) -> sigla interna salva no banco. O modelo do chat
# quase sempre resolve isso sozinho chamando listar_concursos antes (ver SYSTEM_PROMPT_CHAT
# em api.py), mas essa chamada nao e garantida (comportamento de LLM nao e deterministico) -
# esse mapa e uma segunda camada de protecao no proprio codigo, independente do modelo lembrar
# de chamar a ferramenta certa. So cobre os apelidos mais obvios; nao substitui listar_concursos
# pra nomes fora desse mapa.
ALIAS_CONCURSO = {
    'banco do brasil': 'BB',
    'caixa': 'CEF',
    'caixa economica federal': 'CEF',
    'petrobras': 'PETR',
    'ministerio publico de sao paulo': 'MPSP-OP',
    'mpsp': 'MPSP-OP',
    'mpsp oficial de promotoria': 'MPSP-OP',
    'tribunal de justica de sao paulo': 'TJSP',
}


def _normalizar_texto(s: str) -> str:
    sem_acento = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', sem_acento.lower()).strip()


_ROMANOS_PARA_ARABICO = {
    'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'v': '5',
    'vi': '6', 'vii': '7', 'viii': '8', 'ix': '9', 'x': '10',
}


def _canonizar_tokens(texto_norm: str) -> list:
    return [_ROMANOS_PARA_ARABICO.get(tok, tok) for tok in texto_norm.split()]


def _tokens_equivalentes(a: str, b: str) -> bool:
    """Dois tokens batem se forem iguais, ou (pra tokens nao-numericos) um for prefixo do outro
    com pelo menos 2 letras - cobre abreviacao tipo 'op'/'operacao'. Numeros nunca casam por
    prefixo (evita '1' bater com '10', ou pior, o colapso de romanos 'i'/'iii' que gerou o bug
    original de misturar Bloco I com Bloco III)."""
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    menor, maior = (a, b) if len(a) <= len(b) else (b, a)
    return len(menor) >= 2 and maior.startswith(menor)


def _materia_bate(materia_norm: str, tema_norm: str) -> bool:
    """Compara dois nomes de materia ja normalizados como sequencia de tokens equivalentes (nao
    substring crua de string inteira) - substring cru fazia 'op bloco i' bater como prefixo de
    'op bloco iii', misturando Bloco I (Quimica) com Bloco III (Engenharia) no mesmo lote.
    Numerais romanos sao convertidos pra arabico antes de comparar, pra 'Bloco 3' bater com
    'Bloco III', e tokens de texto casam por prefixo (>=2 letras) pra 'Operação' bater com 'Op'."""
    tokens_a = _canonizar_tokens(materia_norm)
    tokens_b = _canonizar_tokens(tema_norm)
    menor, maior = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    n = len(menor)
    if n == 0:
        return False
    for i in range(len(maior) - n + 1):
        if all(_tokens_equivalentes(x, y) for x, y in zip(menor, maior[i:i + n])):
            return True
    return False


def resolver_concurso(concurso: str) -> str:
    return ALIAS_CONCURSO.get(_normalizar_texto(concurso), concurso)

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

SYSTEM_PROMPT_MESTRE_QUESTOES_ABCDE = """Você é um conteudista especializado em concursos públicos, escrevendo questões
comentadas de múltipla escolha (5 alternativas, A a E) no padrão da plataforma Aprova Sim,
com o mesmo nível de profundidade jurídica e didática do material de referência.

REGRAS OBRIGATÓRIAS:
1. Use apenas o TRECHO fornecido como fonte de conteúdo. Nunca cite lei, decreto,
   artigo ou instrução normativa que não apareça literalmente no TRECHO.
2. Qualquer citação legal no campo "comentario" deve ser uma transcrição literal
   de um trecho do TRECHO fornecido, delimitada entre aspas retas (" ").
   Não parafraseie o texto legal citado.
3. Gere exatamente 5 alternativas (A a E), sendo só UMA correta. As alternativas erradas
   devem ser plausíveis (erros sutis, não absurdos óbvios), mas baseadas no TRECHO - não
   invente informação externa nem para as alternativas erradas.
4. Se um EXEMPLO DE REFERÊNCIA for fornecido, use-o só para calibrar tom,
   profundidade e estrutura do comentário (é uma questão real de banca, revisada
   por humano). Nunca copie seu conteúdo nem cite a lei mencionada nele - a
   única fonte válida de citação continua sendo o TRECHO.
5. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

FORMATO DE SAÍDA (JSON):
{
  "enunciado": "...",
  "alternativas": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."},
  "gabarito": "A" ou "B" ou "C" ou "D" ou "E" (a letra da alternativa correta),
  "comentario": "..."
}"""

USER_PROMPT_MESTRE_QUESTOES_ABCDE = """CONCURSO: {concurso}
MATÉRIA: {materia}
TEMA: {tema}
FORMATO: múltipla escolha (A a E)

TRECHO (fonte de verdade, não usar nada fora daqui):
\"\"\"
{trecho}
\"\"\"
{exemplo_calibracao}
Gere 1 questão comentada de múltipla escolha (5 alternativas, A a E) sobre este trecho."""

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
        'formatos': {
            'certo_errado': {
                'system_prompt': SYSTEM_PROMPT_MESTRE_QUESTOES,
                'user_prompt': USER_PROMPT_MESTRE_QUESTOES,
            },
            'abcde': {
                'system_prompt': SYSTEM_PROMPT_MESTRE_QUESTOES_ABCDE,
                'user_prompt': USER_PROMPT_MESTRE_QUESTOES_ABCDE,
            },
        },
        'formato_padrao': 'certo_errado',
        'exigir_citacao': True,
    },
    'revisao_farol': {
        'formatos': {
            None: {
                'system_prompt': SYSTEM_PROMPT_REVISAO_FAROL,
                'user_prompt': USER_PROMPT_REVISAO_FAROL,
            },
        },
        'formato_padrao': None,
        'exigir_citacao': False,
    },
}


PADRAO_CITACAO = re.compile(
    # o modelo deveria usar so aspas retas duplas (instrucao no prompt), mas na pratica usa
    # aspas simples e aspas tipograficas tambem com frequencia real - so aceitar aspas retas
    # duplas rejeitava citacoes corretas, verbatim no trecho, so por causa do estilo de aspas
    r'"([^"]+)"|\'([^\']+)\'|“([^”]+)”|‘([^’]+)’'
)


def _normalizar_para_comparacao_citacao(s: str) -> str:
    """Normalizacao agressiva so pra decidir se uma citacao 'bate' com o trecho - nao muda o
    texto exibido em lugar nenhum. Espaco em volta de simbolos matematicos (ex.: 'A ∪ B' vs
    'A∪B') e indicador ordinal/travessao (13º vs 13°, − vs – vs -) sao trocados com frequencia
    real entre o texto extraido do PDF de origem e o jeito que o modelo reproduz a citacao,
    sem mudar o sentido - normalizar isso evita falso-negativo numa citacao genuinamente
    verbatim, sem abrir mao de pegar citacao realmente inventada (conteudo ausente do trecho)."""
    s = re.sub(r'[−–—]', '-', s)
    s = re.sub(r'[°ºª]', '', s)
    s = re.sub(r'\s+', '', s)
    return s.upper()


def validar_citacao(texto: str, trecho: str, exigir_citacao: bool) -> bool:
    citacoes = [g for m in PADRAO_CITACAO.finditer(texto) for g in m.groups() if g]
    if not citacoes:
        return not exigir_citacao
    trecho_norm = _normalizar_para_comparacao_citacao(trecho)
    for citacao in citacoes:
        citacao_norm = _normalizar_para_comparacao_citacao(citacao)
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
        consulta = consulta.ilike('concurso', concurso)
    resultado = consulta.limit(1).execute()
    if not resultado.data:
        return ''
    exemplo = resultado.data[0]
    return BLOCO_EXEMPLO_CALIBRACAO.format(**exemplo)


def gerar_questao(
    materia: str, tema: str, produto: str = 'mestre_questoes', model: str = 'gpt-4.1',
    concurso: str = None, formato: str = None,
) -> dict:
    if produto not in PRODUTOS:
        raise ProdutoInvalido(f'produto deve ser um de {list(PRODUTOS)}, recebido {produto!r}')
    produto_config = PRODUTOS[produto]
    formato_resolvido = formato or produto_config['formato_padrao']
    if formato_resolvido not in produto_config['formatos']:
        raise ProdutoInvalido(
            f"formato deve ser um de {list(produto_config['formatos'])} pra produto={produto!r}, "
            f'recebido {formato_resolvido!r}'
        )
    config = produto_config['formatos'][formato_resolvido]
    exigir_citacao = produto_config['exigir_citacao']

    supabase = get_supabase()
    openai_client = get_openai()

    consulta_fonte = supabase.table('material_fonte').select('*').eq('materia', materia).eq('tema', tema)
    if concurso:
        consulta_fonte = consulta_fonte.ilike('concurso', resolver_concurso(concurso))
    fonte = consulta_fonte.limit(1).execute()
    if not fonte.data:
        raise MaterialNaoEncontrado(f'nenhum material_fonte para materia={materia!r} tema={tema!r}')
    registro = fonte.data[0]
    trecho = registro['trecho']

    exemplo_calibracao = buscar_exemplo_calibracao(supabase, registro['concurso'], registro['materia'], formato_resolvido)

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
    citacao_ok = validar_citacao(texto_para_validar, trecho, exigir_citacao)
    status = 'pendente_revisao' if citacao_ok else 'rejeitada'
    motivo_rejeicao = None if citacao_ok else 'citacao legal nao encontrada literalmente no material_fonte'

    hash_conteudo = hashlib.sha256(questao['enunciado'].encode('utf-8')).hexdigest()

    insercao = {
        'concurso': registro['concurso'],
        'materia': registro['materia'],
        'tema': registro['tema'],
        'origem': produto,
        'formato': formato_resolvido,
        'status': status,
        'motivo_rejeicao': motivo_rejeicao,
        'enunciado': questao['enunciado'],
        'alternativas': questao.get('alternativas'),
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
        .ilike('concurso', resolver_concurso(concurso))
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


def listar_materias_geracao(concurso: str) -> list:
    """Nomes de materia distintos no material_fonte do concurso (fonte usada pra geracao via
    IA) - diferente de listar_materias, que e sourced de questoes ja aprovadas (usado pra
    simulado). Usado pelo assistente quando o pedido de geracao menciona uma materia/bloco
    especifico, pra descobrir o nome exato salvo no banco (ex.: usuario pede 'Bloco I', o nome
    real e 'Op Bloco I')."""
    supabase = get_supabase()
    resultado = (
        supabase.table('material_fonte')
        .select('materia')
        .ilike('concurso', resolver_concurso(concurso))
        .execute()
    )
    return sorted({linha['materia'] for linha in resultado.data})


def gerar_lote(
    concurso: str, quantidade: int, produto: str = 'mestre_questoes', model: str = 'gpt-4.1',
    formato: str = None, materia: str = None,
) -> dict:
    """Gera `quantidade` questoes novas via IA, uma por tema em round-robin. Nunca reaproveita -
    Mestre em Questoes e sempre 100% gerado. Falhas pontuais (ex.: duplicata de hash) nao derrubam
    o lote inteiro, ficam listadas em 'falhas'. formato (opcional, so vale pra mestre_questoes):
    'certo_errado' (padrao) ou 'abcde'. materia (opcional) restringe a geracao a uma materia
    especifica em vez de round-robin por todo o concurso - sem isso, um pedido tipo 'gere
    questoes do Bloco I' pode sair com qualquer materia do concurso, nao so a pedida.
    Casamento de materia e por substring (case/acento-insensitive) pra tolerar apelidos comuns
    (ex.: usuario pede 'Bloco I', nome real no banco e 'Op Bloco I')."""
    temas = listar_temas(concurso)

    if materia:
        materia_norm = _normalizar_texto(materia)
        temas_filtrados = [
            (m, t) for m, t in temas
            if _materia_bate(materia_norm, _normalizar_texto(m))
        ]
        if not temas_filtrados:
            raise MaterialNaoEncontrado(
                f'nenhuma materia do material_fonte de concurso={concurso!r} bate com materia={materia!r}'
            )
        temas = temas_filtrados

    resultados = []
    falhas = []
    for materia, tema in itertools.islice(itertools.cycle(temas), quantidade):
        try:
            resultados.append(gerar_questao(materia, tema, produto, model, concurso=concurso, formato=formato))
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
    consulta = supabase.table('questoes').select('*').ilike('concurso', resolver_concurso(concurso)).eq('status', 'aprovada')
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


def listar_concursos() -> list:
    """Siglas de concurso com material_fonte cadastrado (habilitadas pra geracao via IA),
    na grafia exata salva no banco - usado pelo assistente antes de gerar_questoes quando o
    usuario menciona o concurso pelo nome por extenso (ex.: 'Banco do Brasil', 'Petrobrás')
    em vez da sigla interna ('BB', 'PETR'), que e o que fica salvo no banco."""
    supabase = get_supabase()
    resultado = supabase.table('material_fonte').select('concurso').execute()
    return sorted({linha['concurso'] for linha in resultado.data})


def listar_materias(concurso: str) -> list:
    """Nomes de materia distintos com estoque aprovado para o concurso, na grafia exata
    salva no banco - usado pelo assistente pra alinhar a distribuicao por materia de um
    simulado antes de chamar sortear_simulado_estratificado (nomes tipo 'RLM' nao sao
    obvios a partir do pedido em linguagem natural do usuario)."""
    supabase = get_supabase()
    resultado = (
        supabase.table('questoes')
        .select('materia')
        .ilike('concurso', resolver_concurso(concurso))
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
