import pypdf, re, json, sys, hashlib, os

try:
    import docx
except ImportError:
    docx = None


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def load_text(path):
    if path.lower().endswith('.docx'):
        if docx is None:
            raise ImportError('python-docx nao instalado - necessario pra ler .docx')
        documento = docx.Document(path)
        return '\n'.join(p.text for p in documento.paragraphs)
    reader = pypdf.PdfReader(path)
    return '\n'.join((p.extract_text() or '') for p in reader.pages)


MATERIA_HEADER_RE = re.compile(r'^([A-ZÀ-Ú][A-ZÀ-Ú\- ]{3,45})\s*$', re.MULTILINE)
LEIA_TEXTO_RE = re.compile(
    r'Leia o texto.*?(?:quest(?:[oõ]es|[aã]o)|itens?)\s+(?:de\s+)?(\d+)\s*(?:a|e|[ea]\s+)\s*(\d+)',
    re.IGNORECASE | re.DOTALL,
)
ITEM_MARCADOR_RE = re.compile(
    # duas formas aceitas: "QUESTAO NN (banca)" (usada em alguns .docx, sem ponto depois do
    # numero) ou "NN." simples (formato mais comum). A pontuacao SO pode ser opcional quando
    # o prefixo "QUESTAO" esta presente - deixar opcional pros dois casos faz qualquer numero
    # solto no meio do enunciado (ex.: "150 minutos") virar falso marcador de item.
    r'^\s*(?:QUEST[AÃ]O\s*0*(\d{1,3})\s*(?:\([^)]*\))?|0*(\d{1,3})\s*\.)\s*',
    re.MULTILINE | re.IGNORECASE,
)
COMENTARIO_RE = re.compile(r'COMENT[AÁ]RIOS?\s*:\s*', re.IGNORECASE)
GABARITO_RE = re.compile(r'GABARITO\s*:\s*([^\n]+)', re.IGNORECASE)
ALTERNATIVA_MARCADOR_RE = re.compile(r'^\(?([A-E])\)\s*', re.MULTILINE)
CERTO_ERRADO_RE = re.compile(r'\(\s*\)\s*Certo', re.IGNORECASE)

MATERIAS_INVALIDAS = {
    'GABARITO', 'COMENTARIOS', 'COMENTÁRIOS', 'CERTO', 'ERRADO',
}


def extrair_alternativas(bloco):
    marcadores = list(ALTERNATIVA_MARCADOR_RE.finditer(bloco))
    if len(marcadores) < 3:
        return None, None
    alternativas = {}
    for i, m in enumerate(marcadores):
        fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(bloco)
        alternativas[m.group(1)] = norm(bloco[m.end():fim])
    return marcadores[0].start(), alternativas


def normalizar_gabarito(formato, gabarito_bruto, alternativas):
    g = gabarito_bruto.strip().upper().rstrip('.')
    if formato == 'certo_errado':
        if g.startswith('C'):
            return 'CERTO'
        if g.startswith('E'):
            return 'ERRADO'
        return None
    if formato == 'abcde':
        letra = g[:1]
        if letra in (alternativas or {}):
            return letra
        return None
    return None


def montar_mapa_materias(texto):
    """Posicao de cada heading de materia (linha toda em caixa alta), na ordem em que aparecem.

    Dois problemas reais do material de origem tratados aqui:
    1. Um heading pode quebrar em 2 linhas por hifenizacao do PDF (ex.: 'RACIOCIONIO LOGICO-'
       seguido de 'MATEMATICO' na linha de baixo, sem linha em branco entre elas) - juntado
       numa unica materia mantendo o hifen.
    2. Texto em caixa alta DENTRO do corpo de uma questao (ex.: cabecalho de coluna de uma
       tabela de dados) tem a MESMA cara de um heading de materia real, mas nao e - um heading
       de verdade so aparece no intervalo ENTRE questoes (depois do GABARITO da anterior e
       antes do marcador da proxima), nunca depois que a proxima questao ja comecou. Candidatos
       que caem dentro do corpo de uma questao (depois do marcador dela, antes do GABARITO
       dela) sao descartados.
    """
    candidatos = []
    for m in MATERIA_HEADER_RE.finditer(texto):
        nome = norm(m.group(1))
        if nome.upper() in MATERIAS_INVALIDAS or len(nome) < 4:
            continue
        candidatos.append((m.start(), m.end(), nome))

    marcadores_item = [im.start() for im in ITEM_MARCADOR_RE.finditer(texto)]
    fins_gabarito = [gm.end() for gm in GABARITO_RE.finditer(texto)]

    def dentro_de_questao(pos):
        # ultimo marcador de item e ultimo fim-de-gabarito antes de pos: se o marcador de
        # item for mais recente que o fim do gabarito, pos esta dentro do corpo dessa questao
        ultimo_item = max((p for p in marcadores_item if p <= pos), default=-1)
        ultimo_gabarito = max((p for p in fins_gabarito if p <= pos), default=-1)
        return ultimo_item > ultimo_gabarito

    candidatos_validos = [c for c in candidatos if not dentro_de_questao(c[0])]

    materias = []
    i = 0
    while i < len(candidatos_validos):
        pos, fim, nome = candidatos_validos[i]
        if i + 1 < len(candidatos_validos):
            prox_pos, prox_fim, prox_nome = candidatos_validos[i + 1]
            entre_linhas = texto[fim:prox_pos]
            # sem linha em branco entre as duas linhas candidatas = continuacao do mesmo heading
            if entre_linhas.count('\n') <= 1:
                separador = '-' if nome.endswith('-') else ' '
                nome = nome.rstrip('-') + separador + prox_nome
                i += 1
        materias.append((pos, nome))
        i += 1
    return materias


def materia_de(pos, mapa_materias):
    materia = None
    for m_pos, nome in mapa_materias:
        if m_pos <= pos:
            materia = nome
        else:
            break
    return materia


def montar_mapa_textos_auxiliares(texto):
    """P/ cada cluster 'Leia o texto ... itens de N a M', guarda o texto auxiliar (do fim
    dessa linha ate o proximo marcador de item) e o range de itens que ele cobre."""
    clusters = []
    matches = list(LEIA_TEXTO_RE.finditer(texto))
    for i, m in enumerate(matches):
        inicio_item, fim_item = int(m.group(1)), int(m.group(2))
        texto_start = m.end()
        prox_item = ITEM_MARCADOR_RE.search(texto, texto_start)
        texto_end = prox_item.start() if prox_item else texto_start
        texto_auxiliar = norm(texto[texto_start:texto_end]).lstrip(':.-• ').strip()
        clusters.append((inicio_item, fim_item, texto_auxiliar))
    return clusters


def texto_auxiliar_de(numero_item, clusters):
    for inicio, fim, texto_auxiliar in clusters:
        if inicio <= numero_item <= fim:
            return texto_auxiliar or None
    return None


def parse_simulado(path, concurso, arquivo_origem=None, origem='simulado_migrado'):
    arquivo_origem = arquivo_origem or os.path.basename(path)
    texto = load_text(path)

    mapa_materias = montar_mapa_materias(texto)
    clusters_texto = montar_mapa_textos_auxiliares(texto)

    comentario_matches = list(COMENTARIO_RE.finditer(texto))
    gabarito_matches = list(GABARITO_RE.finditer(texto))

    registros = []
    falhas = []

    if len(comentario_matches) != len(gabarito_matches):
        falhas.append({
            'numero': None,
            'motivo': f'contagem de COMENTARIOS ({len(comentario_matches)}) difere de GABARITO ({len(gabarito_matches)})',
        })

    limite_anterior = 0
    for i, (cm, gm) in enumerate(zip(comentario_matches, gabarito_matches)):
        bloco_enunciado_bruto = texto[limite_anterior:cm.start()]
        comentario = norm(texto[cm.end():gm.start()])
        gabarito_bruto = gm.group(1)
        limite_anterior = gm.end()

        item_match = None
        for im in ITEM_MARCADOR_RE.finditer(bloco_enunciado_bruto):
            item_match = im  # ultimo marcador de item antes do COMENTARIOS = o item atual
        if item_match is None:
            falhas.append({'numero': None, 'motivo': 'nao achei marcador de item antes de um COMENTARIOS'})
            continue

        numero = int(item_match.group(1) or item_match.group(2))
        bloco = bloco_enunciado_bruto[item_match.end():]

        primeira_alt_pos, alternativas = extrair_alternativas(bloco)
        ce_match = CERTO_ERRADO_RE.search(bloco)
        if alternativas:
            formato = 'abcde'
            enunciado = bloco[:primeira_alt_pos]
        elif ce_match:
            formato = 'certo_errado'
            enunciado = bloco[:ce_match.start()]
        else:
            falhas.append({'numero': numero, 'motivo': 'formato nao identificado (nem abcde nem certo_errado)'})
            continue

        gabarito = normalizar_gabarito(formato, gabarito_bruto, alternativas)
        if gabarito is None:
            falhas.append({'numero': numero, 'motivo': f'gabarito bruto nao reconhecido: {gabarito_bruto!r}'})
            continue

        enunciado_norm = norm(enunciado)
        if not enunciado_norm:
            falhas.append({'numero': numero, 'motivo': 'enunciado vazio apos limpeza'})
            continue

        registros.append({
            'concurso': concurso,
            'materia': materia_de(cm.start(), mapa_materias),
            'tema': None,
            'origem': origem,
            'formato': formato,
            'banca_ano': None,
            'texto_auxiliar': texto_auxiliar_de(numero, clusters_texto),
            'enunciado': enunciado_norm,
            'alternativas': alternativas,
            'gabarito': gabarito,
            'comentario': comentario,
            'arquivo_origem': arquivo_origem,
            'hash_conteudo': hashlib.sha256(enunciado_norm.encode('utf-8')).hexdigest(),
        })

    return registros, falhas


if __name__ == '__main__':
    src = sys.argv[1]
    concurso = sys.argv[2]
    out_path = sys.argv[3]
    registros, falhas = parse_simulado(src, concurso)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)
    print(f'{len(registros)} questoes extraidas, {len(falhas)} falhas -> {out_path}')
    for fa in falhas:
        print(' FALHA:', fa)
