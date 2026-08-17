"""Roda o parser MQ DIGITAL na pasta nova organizada por concurso (OneDrive_1_17-08-2026).
Diferente de rodar_lote_mq_digital.py: concurso vem da SUBPASTA (autoritativo), nao do nome
do arquivo - o nome do arquivo nessa leva tem variacoes demais (MEQ Digital/MeQ Digital,
codigo de concurso com hifen, ate um typo 'MPSO-OP' vs 'MPSP-OP') pra confiar soh nele."""
import glob
import json
import os
import re

from parse_mq_digital import parse_mq_digital

PASTA_BASE = r'C:\Users\trafe\Downloads\OneDrive_1_17-08-2026'
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'dados', 'mq_digital_onedrive')

CONCURSOS = {
    'Banco do Brasil': 'BB',
    'Caixa Econômica Federal': 'CEF',
    'INSS': 'INSS',
    'MPSP - Oficial de Promotoria': 'MPSP-OP',
    'Petrobras': 'PETR',
    'TJSP': 'TJSP',
}

TIPO_RE = re.compile(r'(?:MQE?|MEQ)\s*DIGITAL', re.IGNORECASE)


def extrair_materia(nome_arquivo):
    base = os.path.splitext(nome_arquivo)[0]
    m = TIPO_RE.search(base)
    if not m:
        return None
    materia = base[m.end():].lstrip(' -').strip()
    return materia or None


def main():
    os.makedirs(SAIDA, exist_ok=True)

    resumo = []
    todos_registros = []
    for pasta_concurso, sigla in CONCURSOS.items():
        arquivos = sorted(glob.glob(os.path.join(PASTA_BASE, pasta_concurso, 'Apostila de questões', '*.pdf')))
        for path in arquivos:
            nome = os.path.basename(path)
            materia = extrair_materia(nome)
            if materia is None:
                resumo.append({'arquivo': nome, 'concurso': sigla, 'ok': 0, 'falhas': 0, 'erro': 'nao achei tag de tipo (MQ/MQE/MEQ DIGITAL) no nome'})
                print(f'[     ERRO] {sigla} - {nome}: nao achei tag de tipo no nome')
                continue
            try:
                registros, falhas = parse_mq_digital(path, concurso=sigla, materia=materia)
                todos_registros.extend(registros)
                resumo.append({'arquivo': nome, 'concurso': sigla, 'ok': len(registros), 'falhas': len(falhas)})
                status = 'OK' if not falhas else f'{len(falhas)} falhas'
                print(f'[{status:>10}] {len(registros):>3} questoes - {sigla} - {nome}')
                for fa in falhas:
                    print(f'             falha: {fa}')
            except Exception as e:
                resumo.append({'arquivo': nome, 'concurso': sigla, 'ok': 0, 'falhas': 0, 'erro': str(e)})
                print(f'[     ERRO] {sigla} - {nome}: {e}')

    out_path = os.path.join(SAIDA, 'todas_questoes.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    total_ok = sum(r['ok'] for r in resumo)
    total_falhas = sum(r['falhas'] for r in resumo)
    total_erro = sum(1 for r in resumo if r.get('erro'))
    print(f'\n=== TOTAL: {total_ok} questoes extraidas, {total_falhas} falhas pontuais, {total_erro} arquivos com erro fatal ===')
    print(f'Gravado em: {out_path}')


if __name__ == '__main__':
    main()
