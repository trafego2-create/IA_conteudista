import glob
import json
import os
import sys

from parse_mq_digital import parse_mq_digital

PASTA = r'C:\Users\trafe\Downloads\Apostilas Base de Conteudo'
SAIDA = os.path.join(os.path.dirname(__file__), '..', 'dados', 'mq_digital')


def main():
    os.makedirs(SAIDA, exist_ok=True)
    arquivos = sorted(
        f for f in glob.glob(os.path.join(PASTA, '*.pdf'))
        if 'MQ DIGITAL' in os.path.basename(f).upper() or 'MQE DIGITAL' in os.path.basename(f).upper()
    )
    print(f'{len(arquivos)} arquivos encontrados\n')

    resumo = []
    todos_registros = []
    for path in arquivos:
        nome = os.path.basename(path)
        try:
            registros, falhas = parse_mq_digital(path)
            todos_registros.extend(registros)
            resumo.append({'arquivo': nome, 'ok': len(registros), 'falhas': len(falhas), 'erro': None})
            status = 'OK' if not falhas else f'{len(falhas)} falhas'
            print(f'[{status:>10}] {len(registros):>3} questoes - {nome}')
            for fa in falhas:
                print(f'             falha: {fa}')
        except Exception as e:
            resumo.append({'arquivo': nome, 'ok': 0, 'falhas': 0, 'erro': str(e)})
            print(f'[     ERRO] {nome}: {e}')

    out_path = os.path.join(SAIDA, 'todas_questoes.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(todos_registros, f, ensure_ascii=False, indent=2)

    resumo_path = os.path.join(SAIDA, 'resumo.json')
    with open(resumo_path, 'w', encoding='utf-8') as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    total_ok = sum(r['ok'] for r in resumo)
    total_falhas = sum(r['falhas'] for r in resumo)
    total_erro = sum(1 for r in resumo if r['erro'])
    print(f'\n=== TOTAL: {total_ok} questoes extraidas, {total_falhas} falhas pontuais, {total_erro} arquivos com erro fatal ===')
    print(f'Gravado em: {out_path}')


if __name__ == '__main__':
    main()
