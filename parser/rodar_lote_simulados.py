import glob
import json
import os

from parse_simulado_antigo import parse_simulado

PASTA_BASE = r'C:\Users\trafe\Downloads\OneDrive_1_17-08-2026'
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'dados', 'simulados_antigos')

CONCURSOS = {
    'Banco do Brasil': 'BB',
    'INSS': 'INSS',
    'TJSP': 'TJSP',
}


def main():
    os.makedirs(SAIDA, exist_ok=True)

    resumo = []
    todos_registros = []
    for pasta_concurso, sigla in CONCURSOS.items():
        arquivos = sorted(glob.glob(os.path.join(PASTA_BASE, pasta_concurso, 'Simulados', '*.pdf')))
        for path in arquivos:
            nome = os.path.basename(path)
            try:
                registros, falhas = parse_simulado(path, sigla)
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
    print(f'\n=== TOTAL: {total_ok} questoes extraidas, {total_falhas} falhas pontuais ===')
    print(f'Gravado em: {out_path}')


if __name__ == '__main__':
    main()
