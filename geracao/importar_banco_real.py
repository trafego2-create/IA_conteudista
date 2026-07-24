import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import get_supabase  # noqa: E402

CAMPOS_TABELA = (
    'concurso', 'materia', 'tema', 'origem', 'formato', 'banca_ano', 'status',
    'texto_auxiliar', 'enunciado', 'alternativas', 'gabarito', 'comentario',
    'arquivo_origem', 'hash_conteudo',
)

LOTE = 500


def carregar_registros(path):
    with open(path, encoding='utf-8') as f:
        registros = json.load(f)
    for r in registros:
        r['status'] = 'pendente_revisao'
    return [{k: r[k] for k in CAMPOS_TABELA} for r in registros]


def importar(path, concurso=None):
    registros = carregar_registros(path)
    if concurso:
        registros = [r for r in registros if r['concurso'] == concurso]
    if not registros:
        print('nenhum registro para importar')
        return

    supabase = get_supabase()
    total_inseridas = 0
    total_duplicadas_ignoradas = 0

    for i in range(0, len(registros), LOTE):
        lote = registros[i:i + LOTE]
        resultado = (
            supabase.table('questoes')
            .upsert(lote, on_conflict='concurso,hash_conteudo', ignore_duplicates=True)
            .execute()
        )
        inseridas_no_lote = len(resultado.data)
        total_inseridas += inseridas_no_lote
        total_duplicadas_ignoradas += len(lote) - inseridas_no_lote
        print(f'lote {i // LOTE + 1}: {inseridas_no_lote}/{len(lote)} inseridas (resto ja existia)')

    print(f'\n=== TOTAL: {total_inseridas} questoes novas inseridas, '
          f'{total_duplicadas_ignoradas} ja existiam (hash_conteudo duplicado) ===')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arquivo', default=os.path.join(
        os.path.dirname(__file__), '..', 'dados', 'mq_digital', 'todas_questoes.json'
    ))
    parser.add_argument('--concurso', default=None, help='filtra so um concurso (ex.: INSS)')
    args = parser.parse_args()

    if not os.path.exists(args.arquivo):
        print(f'arquivo nao encontrado: {args.arquivo}')
        sys.exit(1)

    importar(args.arquivo, args.concurso)
