import pypdf, re, json, sys, hashlib

try:
    import docx
except ImportError:
    docx = None

def load_pages(path):
    if path.lower().endswith('.docx'):
        if docx is None:
            raise ImportError('python-docx nao instalado - necessario pra ler .docx')
        # docx nao tem conceito de "pagina" acessivel via python-docx - trata o documento
        # inteiro como uma pagina so (perde so o strip de cabecalho repetido por pagina,
        # que e cosmetico; a ancoragem por sumario funciona igual)
        documento = docx.Document(path)
        return ['\n'.join(p.text for p in documento.paragraphs)]
    reader = pypdf.PdfReader(path)
    return [(p.extract_text() or '') for p in reader.pages]

def norm(s):
    return re.sub(r'\s+', ' ', s).strip()

def find_dividers(pages):
    dividers = []
    for i, text in enumerate(pages):
        stripped = text.replace('CONCURSOS', '')
        lines = [l.strip() for l in stripped.splitlines() if l.strip()]
        if not lines:
            continue
        joined = ' '.join(lines)
        if len(joined) < 60 and joined.upper() == joined:
            if text.strip().startswith('CONCURSOS') and text.strip().endswith('CONCURSOS'):
                dividers.append((i, joined))
    return dividers

def parse_sumario(text):
    temas = []
    for line in text.splitlines():
        m = re.match(r'^(.*?)\s*\.{2,}\s*(\d+)\s*$', line.strip())
        if m:
            tema = m.group(1).rstrip('. ').strip()
            if tema:
                temas.append((norm(tema), int(m.group(2))))
    if temas:
        return temas
    # fallback: sumario simples sem preenchimento de pontos nem numero de pagina, so uma
    # lista curta de titulos (ex.: apostilas de materia unica com poucos temas, tipo
    # "Decreto Nº 1.171" / "Decreto Nº 6.029" soltos). So considera linhas DEPOIS da
    # palavra "Sumario" em si, senao pega lixo do cabecalho/titulo da pagina.
    m_sumario = re.search(r'Sum[aá]rio', text, re.IGNORECASE)
    if not m_sumario:
        return temas
    ordem = 0
    for line in text[m_sumario.end():].splitlines():
        candidate = norm(line)
        if not candidate or candidate.isdigit() or len(candidate) > 80:
            continue
        ordem += 1
        temas.append((candidate, ordem))
    return temas

def strip_header(text, materia_upper):
    lines = text.split('\n')
    idx = 0
    while idx < len(lines) and idx < 6:
        candidate = norm(lines[idx])
        if candidate == '' or candidate == 'CONCURSOS' or candidate.isdigit():
            idx += 1
            continue
        if candidate.upper() == materia_upper or candidate.upper() in materia_upper or materia_upper in candidate.upper():
            idx += 1
            continue
        break
    return '\n'.join(lines[idx:])

def build_stripped(text):
    kept_chars = []
    index_map = []
    for i, ch in enumerate(text):
        if ch.isalnum() or ch.isspace():
            kept_chars.append(ch.upper())
            index_map.append(i)
    return ''.join(kept_chars), index_map

def find_all_fuzzy(full_stripped, index_map, tema):
    tema_stripped, _ = build_stripped(tema)
    positions = []
    start = 0
    while True:
        pos = full_stripped.find(tema_stripped, start)
        if pos == -1:
            break
        positions.append(index_map[pos])
        start = pos + 1
    if positions:
        return positions
    # tolera sufixos divergentes entre sumario e corpo (ex.: ano abreviado em
    # numero de decreto) usando so os primeiros ~60% do titulo como ancora
    prefix_len = max(8, int(len(tema_stripped) * 0.6))
    prefix = tema_stripped[:prefix_len]
    start = 0
    while True:
        pos = full_stripped.find(prefix, start)
        if pos == -1:
            break
        positions.append(index_map[pos])
        start = pos + 1
    return positions

def page_number_of(text):
    m = re.match(r'^CONCURSOS\s*\n(\d+)\s*\n', text)
    return int(m.group(1)) if m else None

def parse_apostila(path, concurso, arquivo_origem):
    pages = load_pages(path)
    dividers = find_dividers(pages)
    registros = []
    for idx, (div_page, materia_joined) in enumerate(dividers):
        materia = norm(materia_joined)
        sumario_page_idx = div_page + 1
        sumario_text = pages[sumario_page_idx] if sumario_page_idx < len(pages) else ''
        temas = parse_sumario(sumario_text)
        content_start = sumario_page_idx + 1
        content_end = dividers[idx + 1][0] if idx + 1 < len(dividers) else len(pages)

        # monta full_norm concatenando paginas ja normalizadas individualmente,
        # guardando o intervalo de cada pagina em full_norm para poder
        # descobrir a pagina de qualquer posicao (e desempatar ancoras
        # ambiguas pelo numero de pagina esperado no sumario)
        page_spans = []  # (start, end, pagina_impressa)
        parts = []
        cursor = 0
        for p in range(content_start, content_end):
            raw = pages[p]
            pn = page_number_of(raw)
            cleaned = norm(strip_header(raw, materia))
            if not cleaned:
                continue
            start = cursor
            parts.append(cleaned)
            cursor += len(cleaned) + 1
            page_spans.append((start, cursor - 1, pn))
        full_norm = ' '.join(parts)

        def page_of(pos):
            for start, end, pn in page_spans:
                if start <= pos <= end:
                    return pn
            return None

        full_stripped, index_map = build_stripped(full_norm)
        # resolve na ORDEM DO SUMARIO (verdade do documento), nao pela posicao
        # bruta do match, e exige posicoes crescentes: se o melhor candidato
        # por pagina vier antes do tema anterior, troca pelo primeiro
        # candidato que respeite a ordem do documento.
        anchors = []
        prev_pos = -1
        for tema, expected_page in temas:
            candidates = sorted(find_all_fuzzy(full_stripped, index_map, tema))
            if not candidates:
                continue
            valid = [c for c in candidates if c > prev_pos]
            pool = valid if valid else candidates
            best = min(pool, key=lambda pos: abs((page_of(pos) or expected_page) - expected_page))
            anchors.append((best, tema))
            prev_pos = best

        for i, (pos, tema) in enumerate(anchors):
            end = anchors[i + 1][0] if i + 1 < len(anchors) else len(full_norm)
            trecho_norm = full_norm[pos:end].strip()
            registros.append({
                'concurso': concurso,
                'arquivo_origem': arquivo_origem,
                'materia': materia,
                'tema': tema,
                'ordem': i,
                'pagina': page_of(pos),
                'trecho': trecho_norm,
                'hash_conteudo': hashlib.sha256(trecho_norm.encode('utf-8')).hexdigest(),
            })
    return registros

def find_sumario_page(pages):
    for i, text in enumerate(pages):
        if re.search(r'^\s*Sum[aá]rio\s*$', text, re.IGNORECASE | re.MULTILINE):
            return i
    return None


def parse_apostila_single(path, concurso, materia, arquivo_origem):
    """Variante de parse_apostila pra arquivo de UMA materia so (sem os divisores
    'CONCURSOS...CONCURSOS' entre materias da apostila combinada original) - formato usado
    nos arquivos '01 - BB - Português Básico.pdf' etc. Reaproveita a mesma logica de ancoragem
    por sumario, so sem o loop externo por materia (aqui so tem uma, dada explicitamente)."""
    pages = load_pages(path)
    sumario_page_idx = find_sumario_page(pages)
    if sumario_page_idx is None:
        raise ValueError('pagina de Sumario nao encontrada')
    sumario_text = pages[sumario_page_idx]
    temas = parse_sumario(sumario_text)
    if not temas:
        raise ValueError('nenhum tema encontrado no Sumario')
    content_start = sumario_page_idx + 1
    content_end = len(pages)
    materia_upper = materia.upper()

    page_spans = []
    parts = []
    cursor = 0
    for p in range(content_start, content_end):
        raw = pages[p]
        pn = page_number_of(raw)
        cleaned = norm(strip_header(raw, materia_upper))
        if not cleaned:
            continue
        start = cursor
        parts.append(cleaned)
        cursor += len(cleaned) + 1
        page_spans.append((start, cursor - 1, pn))
    full_norm = ' '.join(parts)

    def page_of(pos):
        for start, end, pn in page_spans:
            if start <= pos <= end:
                return pn
        return None

    full_stripped, index_map = build_stripped(full_norm)
    anchors = []
    prev_pos = -1
    for tema, expected_page in temas:
        candidates = sorted(find_all_fuzzy(full_stripped, index_map, tema))
        if not candidates:
            continue
        valid = [c for c in candidates if c > prev_pos]
        pool = valid if valid else candidates
        best = min(pool, key=lambda pos: abs((page_of(pos) or expected_page) - expected_page))
        anchors.append((best, tema))
        prev_pos = best

    registros = []
    for i, (pos, tema) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(full_norm)
        trecho_norm = full_norm[pos:end].strip()
        registros.append({
            'concurso': concurso,
            'arquivo_origem': arquivo_origem,
            'materia': materia,
            'tema': tema,
            'ordem': i,
            'pagina': page_of(pos),
            'trecho': trecho_norm,
            'hash_conteudo': hashlib.sha256(trecho_norm.encode('utf-8')).hexdigest(),
        })
    return registros


def parse_apostila_docx_por_heading(path, concurso, materia, arquivo_origem):
    """Variante pra .docx cujo 'Sumario' e um campo de TOC automatico do Word - o texto do
    campo fica vazio quando lido via python-docx (nao e texto literal, e um campo calculado),
    entao a ancoragem por sumario textual (parse_apostila_single) nao acha nada mesmo o
    documento tendo secoes de verdade. Mais confiavel nesse caso: usar o estilo 'Heading 1'
    do proprio Word como marcador de tema, ja que reflete a estrutura real do documento."""
    if docx is None:
        raise ImportError('python-docx nao instalado - necessario pra ler .docx')
    documento = docx.Document(path)
    paragrafos = documento.paragraphs

    indices_heading = [
        i for i, p in enumerate(paragrafos)
        if p.style and p.style.name == 'Heading 1' and p.text.strip()
    ]
    if not indices_heading:
        raise ValueError('nenhum paragrafo com estilo "Heading 1" encontrado')

    registros = []
    for ordem, idx in enumerate(indices_heading):
        tema = norm(paragrafos[idx].text)
        fim = indices_heading[ordem + 1] if ordem + 1 < len(indices_heading) else len(paragrafos)
        textos = [norm(p.text) for p in paragrafos[idx:fim] if p.text.strip()]
        trecho_norm = ' '.join(textos).strip()
        if not trecho_norm:
            continue
        registros.append({
            'concurso': concurso,
            'arquivo_origem': arquivo_origem,
            'materia': materia,
            'tema': tema,
            'ordem': ordem,
            'pagina': None,
            'trecho': trecho_norm,
            'hash_conteudo': hashlib.sha256(trecho_norm.encode('utf-8')).hexdigest(),
        })
    return registros


if __name__ == '__main__':
    src = sys.argv[1]
    concurso = sys.argv[2]
    arquivo_origem = sys.argv[3]
    out_path = sys.argv[4]
    registros = parse_apostila(src, concurso, arquivo_origem)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)
    print(f'{len(registros)} registros gravados em {out_path}')
    by_materia = {}
    for r in registros:
        by_materia.setdefault(r['materia'], []).append(r['tema'])
    with open(out_path + '.summary.txt', 'w', encoding='utf-8') as f:
        for m, temas in by_materia.items():
            f.write(f'- {m}: {len(temas)} temas -> {temas}\n')
