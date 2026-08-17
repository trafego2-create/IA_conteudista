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


def parse_filename(path):
    """'01 - INSS - MQ DIGITAL - Ética no Serviço Público.pdf' -> (INSS, Ética no Serviço Público)
    'TJSP - MQ DIGITAL - Dir Administrativo.pdf' -> (TJSP, Dir Administrativo) (sem numero de ordem)."""
    base = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r'^(?:\d+\s*-\s*)?([A-ZÀ-Ú]+)\s*-\s*MQE?\s*DIGITAL\s*-\s*(.+)$', base, re.IGNORECASE)
    if not m:
        raise ValueError(f'nome de arquivo fora do padrao esperado: {base!r}')
    return norm(m.group(1)).upper(), norm(m.group(2))


def parse_sumario(text):
    """Mesmo formato de linha-guia usado nas apostilas Esquematizada."""
    temas = []
    for line in text.splitlines():
        m = re.match(r'^(.*?)\s*\.{2,}\s*(\d+)\s*$', line.strip())
        if m:
            tema = m.group(1).rstrip('. ').strip()
            if tema:
                temas.append(norm(tema))
    return temas


def split_sumario_and_body(text):
    m = re.search(r'\n\s*Sum[aá]rio\s*\n', text, re.IGNORECASE)
    if not m:
        # alguns .docx nao tem secao de Sumario (diferente dos PDFs) - degrada
        # graciosamente: sem sumario nao da pra ancorar 'tema' (fica None pra
        # todo mundo), mas a extracao de enunciado/comentario/gabarito nao
        # depende disso, continua funcionando normalmente
        return '', text
    sumario_start = m.end()
    # sumario termina no proximo heading real (primeira linha em CAIXA ALTA
    # que nao seja uma entrada de sumario, ou ate 40 linhas de distancia)
    depois = text[sumario_start:]
    sumario_lines = []
    body_start_offset = None
    cursor = 0
    for line in depois.splitlines(keepends=True):
        stripped = line.strip()
        if re.match(r'^.*\.{2,}\s*\d+\s*$', stripped):
            sumario_lines.append(stripped)
        elif stripped == '' or stripped.isdigit():
            pass
        else:
            body_start_offset = cursor
            break
        cursor += len(line)
    if body_start_offset is None:
        raise ValueError('corpo do documento nao encontrado apos o sumario')
    return '\n'.join(sumario_lines), depois[body_start_offset:]


def locate_temas(body, temas):
    """Posicao da primeira ocorrencia de cada heading de tema no corpo, na ordem do sumario."""
    anchors = []
    search_from = 0
    for tema in temas:
        pos = body.find(tema, search_from)
        if pos == -1:
            # tolera pequenas divergencias de acentuacao/espacamento: procura so pelo prefixo
            prefix = tema[:max(8, int(len(tema) * 0.6))]
            pos = body.find(prefix, search_from)
        if pos != -1:
            anchors.append((pos, tema))
            search_from = pos + 1
    return anchors


def tema_of(pos, anchors):
    tema = None
    for anchor_pos, anchor_tema in anchors:
        if anchor_pos <= pos:
            tema = anchor_tema
        else:
            break
    return tema


QUESTAO_ENUNCIADO_RE = re.compile(
    # \b depois do numero e obrigatorio: sem ele, o motor de regex faz
    # backtracking de \d+ (ex.: captura so "0" de "01") so pra escapar do
    # lookahead negativo, gerando matches truncados/falsos. O \b forca o
    # numero inteiro a ser consumido antes de checar o lookahead.
    # O lookahead em si evita casar com o cabecalho "QUESTAO NN\nCOMENTARIO:"
    # do bloco de comentarios (mesmo padrao de numero, contexto diferente).
    r'QUEST[AÃ]O\s*0*(\d+)\b(?!\s*\n\s*COMENT[AÁ]RIO)\s*[:.\-–]?\s*(?:\(([^)]*)\))?\s*',
    re.IGNORECASE,
)
QUESTAO_COMENTARIO_RE = re.compile(
    r'QUEST[AÃ]O\s*0*(\d+)\s*\n\s*COMENT[AÁ]RIO\s*:\s*(.*?)\n\s*Gabarito\s*:\s*([^\n]+)',
    re.IGNORECASE | re.DOTALL,
)
ALTERNATIVA_MARCADOR_RE = re.compile(r'^([A-E])\)\s*', re.MULTILINE)
CERTO_ERRADO_RE = re.compile(r'\(\s*\)\s*Certo', re.IGNORECASE)


def extrair_alternativas(bloco):
    """Cada alternativa vai de um marcador 'X)' ate o proximo (ou ate o fim do bloco) -
    nao ate o fim da LINHA. Alternativas reais quase sempre quebram em varias linhas no
    PDF (paragrafos inteiros, as vezes quase identicos de proposito, pegadinha classica de
    banca) - pegar so a primeira linha truncava o texto de cada opcao no meio da frase."""
    marcadores = list(ALTERNATIVA_MARCADOR_RE.finditer(bloco))
    if len(marcadores) < 3:
        return None, None
    alternativas = {}
    for i, m in enumerate(marcadores):
        letra = m.group(1)
        fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(bloco)
        alternativas[letra] = norm(bloco[m.end():fim])
    return marcadores[0].start(), alternativas


def parse_enunciados(body):
    """Retorna lista de dicts: numero, banca_ano, enunciado, formato, alternativas, pos."""
    matches = list(QUESTAO_ENUNCIADO_RE.finditer(body))
    registros = []
    for i, m in enumerate(matches):
        numero = int(m.group(1))
        banca_ano = norm(m.group(2)) if m.group(2) else None
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        bloco = body[start:end]

        formato = None
        enunciado = bloco

        primeira_pos, alternativas = extrair_alternativas(bloco)
        ce_match = CERTO_ERRADO_RE.search(bloco)
        if alternativas:
            formato = 'abcde'
            enunciado = bloco[:primeira_pos]
        elif ce_match:
            formato = 'certo_errado'
            enunciado = bloco[:ce_match.start()]

        registros.append({
            'numero': numero,
            'banca_ano': banca_ano,
            'enunciado': norm(enunciado),
            'formato': formato,
            'alternativas': alternativas,
            'pos': m.start(),
        })
    return registros


def comentarios_texto(body):
    """O documento intercala secoes (enunciados de uma secao, heading
    "COMENTARIOS", comentarios da mesma secao, enunciados da proxima secao,
    e por vezes nem repete o heading pra secao seguinte). So existe garantia
    de UM heading "COMENTARIOS" antes do primeiro bloco de comentarios - dali
    pra frente e so procurar pelo padrao "QUESTAO NN\\nCOMENTARIO:...Gabarito:"
    em todo o resto do documento, que e auto-delimitado e ignora com seguranca
    qualquer enunciado de secao seguinte no meio do caminho."""
    m = re.search(r'\n\s*COMENT[AÁ]RIOS\s*\n', body, re.IGNORECASE)
    if not m:
        raise ValueError('secao "COMENTARIOS" nao encontrada')
    return body[m.end():]


def parse_comentarios(trecho):
    """Retorna lista ordenada de (numero_local, comentario, gabarito_bruto).

    A numeracao das questoes reinicia a cada secao/decreto, tanto no bloco de
    enunciados quanto no bloco de comentarios - nao da pra casar pelo numero
    isolado (colide entre secoes)."""
    out = []
    for cm in QUESTAO_COMENTARIO_RE.finditer(trecho):
        numero = int(cm.group(1))
        comentario = norm(cm.group(2))
        gabarito_bruto = norm(cm.group(3))
        out.append((numero, comentario, gabarito_bruto))
    return out


def split_por_reinicio(itens, numero_de):
    """Agrupa uma sequencia em blocos, cortando sempre que o numero da questao cai
    (reinicio de numeracao = nova secao/tema no documento de origem). Cada bloco
    interno tem numeros proprios, sem colisao com os vizinhos."""
    blocos = []
    atual = []
    anterior = None
    for item in itens:
        n = numero_de(item)
        if anterior is not None and n < anterior:
            blocos.append(atual)
            atual = []
        atual.append(item)
        anterior = n
    if atual:
        blocos.append(atual)
    return blocos


def normalizar_gabarito(formato, gabarito_bruto, alternativas):
    g = gabarito_bruto.strip().upper().rstrip('.')
    if formato == 'certo_errado':
        if g.startswith('C'):
            return 'CERTO'
        if g.startswith('E'):
            return 'ERRADO'
        return None
    if formato == 'abcde':
        if g in (alternativas or {}):
            return g
        letra = g[:1]
        if letra in (alternativas or {}):
            return letra
        return None
    return None


def parse_mq_digital(path, concurso=None, materia=None):
    if concurso is None or materia is None:
        f_concurso, f_materia = parse_filename(path)
        concurso = concurso or f_concurso
        materia = materia or f_materia
    arquivo_origem = os.path.basename(path)

    full_text = load_text(path)
    sumario_text, body = split_sumario_and_body(full_text)
    temas = parse_sumario(sumario_text)
    anchors = locate_temas(body, temas)

    enunciados = parse_enunciados(body)
    comentarios = parse_comentarios(comentarios_texto(body))

    # A numeracao reinicia a cada secao tanto no bloco de enunciados quanto no
    # de comentarios, mas as duas listas nem sempre tem exatamente os mesmos
    # itens por secao (uma questao ocasionalmente falta de um lado ou do
    # outro no PDF de origem). Casar pela posicao global faz um unico item
    # deslocado contaminar todo o resto do arquivo. Em vez disso: quebra as
    # duas listas em blocos por reinicio de numeracao (cada bloco = 1 secao),
    # casa bloco com bloco na mesma ordem, e dentro de cada bloco casa por
    # numero local (chave), que isola qualquer item faltante/sobrando so
    # naquela secao especifica.
    blocos_enun = split_por_reinicio(enunciados, lambda e: e['numero'])
    blocos_coment = split_por_reinicio(comentarios, lambda c: c[0])

    registros = []
    falhas = []

    if len(blocos_enun) != len(blocos_coment):
        falhas.append({
            'numero': None,
            'motivo': (
                f'numero de secoes (reinicios de numeracao) diverge entre enunciados '
                f'({len(blocos_enun)}) e comentarios ({len(blocos_coment)}) - '
                f'arquivo pode ter estrutura fora do padrao, revisar manualmente'
            ),
        })

    for bloco_e, bloco_c in zip(blocos_enun, blocos_coment):
        coment_por_numero = {c[0]: (c[1], c[2]) for c in bloco_c}
        for e in bloco_e:
            numero = e['numero']
            if e['formato'] is None:
                falhas.append({'numero': numero, 'motivo': 'formato nao identificado (nem abcde nem certo_errado)'})
                continue
            if numero not in coment_por_numero:
                falhas.append({'numero': numero, 'motivo': 'sem comentario/gabarito correspondente nesta secao'})
                continue
            comentario, gabarito_bruto = coment_por_numero[numero]
            gabarito = normalizar_gabarito(e['formato'], gabarito_bruto, e['alternativas'])
            if gabarito is None:
                falhas.append({'numero': numero, 'motivo': f'gabarito bruto nao reconhecido: {gabarito_bruto!r}'})
                continue

            enunciado_completo = e['enunciado']
            registros.append({
                'concurso': concurso,
                'materia': materia,
                'tema': tema_of(e['pos'], anchors),
                'origem': 'banco_real',
                'formato': e['formato'],
                'banca_ano': e['banca_ano'],
                'texto_auxiliar': None,
                'enunciado': enunciado_completo,
                'alternativas': e['alternativas'],
                'gabarito': gabarito,
                'comentario': comentario,
                'arquivo_origem': arquivo_origem,
                'hash_conteudo': hashlib.sha256(enunciado_completo.encode('utf-8')).hexdigest(),
            })

    return registros, falhas


if __name__ == '__main__':
    src = sys.argv[1]
    out_path = sys.argv[2]
    registros, falhas = parse_mq_digital(src)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)
    print(f'{len(registros)} questoes extraidas, {len(falhas)} falhas -> {out_path}')
    for fa in falhas:
        print(' FALHA:', fa)
