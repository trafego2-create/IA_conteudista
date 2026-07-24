import argparse
import csv
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import get_supabase  # noqa: E402

csv.field_size_limit(sys.maxsize)

CAMPOS = ('concurso', 'arquivo_origem', 'materia', 'tema', 'ordem', 'pagina', 'trecho', 'hash_conteudo')
LOTE = 500


def carregar_registros(path):
    registros = []
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for linha in reader:
            registros.append({
                'concurso': linha['concurso'],
                'arquivo_origem': linha['arquivo_origem'],
                'materia': linha['materia'],
                'tema': linha['tema'],
                'ordem': int(linha['ordem']),
                'pagina': int(linha['pagina']) if linha['pagina'] else None,
                'trecho': linha['trecho'],
                'hash_conteudo': linha['hash_conteudo'],
            })
    return registros


def importar(path):
    registros = carregar_registros(path)
    if not registros:
        print('nenhum registro para importar')
        return

    supabase = get_supabase()
    total_inseridos = 0
    total_duplicados = 0

    for i in range(0, len(registros), LOTE):
        lote = registros[i:i + LOTE]
        resultado = (
            supabase.table('material_fonte')
            .upsert(lote, on_conflict='concurso,arquivo_origem,hash_conteudo', ignore_duplicates=True)
            .execute()
        )
        inseridos_no_lote = len(resultado.data)
        total_inseridos += inseridos_no_lote
        total_duplicados += len(lote) - inseridos_no_lote
        print(f'lote {i // LOTE + 1}: {inseridos_no_lote}/{len(lote)} inseridos (resto ja existia)')

    print(f'\n=== TOTAL: {total_inseridos} registros novos, {total_duplicados} ja existiam ===')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arquivo', default='C:/Users/trafe/Downloads/aprovasim-material-fonte-seed-inss.csv')
    args = parser.parse_args()

    if not os.path.exists(args.arquivo):
        print(f'arquivo nao encontrado: {args.arquivo}')
        sys.exit(1)

    importar(args.arquivo)
