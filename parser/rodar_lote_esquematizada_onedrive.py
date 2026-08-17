"""Roda parse_apostila_single em todas as 'Apostilas teóricas' (uma materia por arquivo) da
pasta OneDrive_1_17-08-2026, organizada por concurso. Concurso vem da subpasta (autoritativo);
materia vem do nome do arquivo, tolerando variacoes reais encontradas: numeracao opcional
('01 - '), tag 'Esquematizada' opcional (BB nao usa, INSS/TJSP/PETR/MPSP/CEF usam), e arquivos
sem nenhuma estrutura de nome (ex.: 'Informática.pdf' solto) onde o nome inteiro vira materia."""
import glob
import json
import os
import re

from parse_apostila import parse_apostila_single

PASTA_BASE = r'C:\Users\trafe\Downloads\OneDrive_1_17-08-2026'
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'dados', 'material_fonte_onedrive')

CONCURSOS = {
    'Banco do Brasil': 'BB',
    'INSS': 'INSS',
    'MPSP - Oficial de Promotoria': 'MPSP-OP',
    'Petrobras': 'PETR',
    'TJSP': 'TJSP',
    'Caixa Econômica Federal': 'CEF',
}


TAG_ESQUEMATIZADA_RE = re.compile(r'Esquematizada\s*-\s*', re.IGNORECASE)


def extrair_materia(nome_arquivo, sigla):
    base = os.path.splitext(nome_arquivo)[0]
    # se tiver a tag "Esquematizada", materia e tudo que vem depois dela, onde quer que
    # esteja no nome - mais robusto que assumir prefixo fixo "NN - CONCURSO -", que varia
    # (ex.: Petrobras usa "PETROBRAS -" no arquivo mas o concurso na pasta e "PETR")
    m = TAG_ESQUEMATIZADA_RE.search(base)
    if m:
        return base[m.end():].strip() or None
    # sem tag (ex.: BB nao usa "Esquematizada" no nome): so tira numeracao e prefixo de
    # concurso conhecidos
    base = re.sub(r'^\d+\s*-\s*', '', base)
    base = re.sub(rf'^{re.escape(sigla)}\s*-\s*', '', base, flags=re.IGNORECASE)
    return base.strip() or None


def main():
    os.makedirs(SAIDA, exist_ok=True)

    resumo = []
    todos_registros = []
    for pasta_concurso, sigla in CONCURSOS.items():
        arquivos = sorted(glob.glob(os.path.join(PASTA_BASE, pasta_concurso, 'Apostilas teóricas', '*.pdf')))
        for path in arquivos:
            nome = os.path.basename(path)
            materia = extrair_materia(nome, sigla)
            try:
                registros = parse_apostila_single(path, sigla, materia, nome)
                todos_registros.extend(registros)
                resumo.append({'arquivo': nome, 'concurso': sigla, 'materia': materia, 'temas': len(registros)})
                print(f'[{len(registros):>3} temas] {sigla} - {nome} -> materia={materia!r}')
            except Exception as e:
                resumo.append({'arquivo': nome, 'concurso': sigla, 'materia': materia, 'erro': str(e)})
                print(f'[  ERRO ] {sigla} - {nome} -> materia={materia!r}: {e}')

    out_path = os.path.join(SAIDA, 'todos_registros.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    total_ok = sum(r.get('temas', 0) for r in resumo)
    total_erro = sum(1 for r in resumo if r.get('erro'))
    print(f'\n=== TOTAL: {total_ok} temas/trechos extraidos, {total_erro} arquivos com erro ===')
    print(f'Gravado em: {out_path}')


if __name__ == '__main__':
    main()
