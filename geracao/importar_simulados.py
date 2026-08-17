"""Importa questoes de simulados antigos migrados (origem='simulado_migrado').

Vao direto como 'aprovada' (decisao do time: ja eram usados/revisados quando eram simulados
antigos, antes da plataforma existir) - EXCETO questoes que citam conteudo visual (imagem,
figura, tira, grafico) que nao existe no texto extraido do PDF, que ficam 'pendente_revisao'
ja que o enunciado sozinho pode estar incompleto/incompreensivel sem a imagem."""
import argparse
import json
import os
import re
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

DEPENDE_DE_IMAGEM_RE = re.compile(
    r'\b(imagem|figura|tira|quadrinho|gr[aá]fico|ilustra[cç][aã]o|foto(?:grafia)?|mapa)\s+a\s+seguir\b'
    r'|\bleitura\s+da\s+tira\b'
    r'|\bcom\s+base\s+n[ao]\s+(imagem|figura|tira|gr[aá]fico)\b'
    r'|\bobserve\s+a\s+(imagem|figura|tira|gr[aá]fico)\b',
    re.IGNORECASE,
)


def depende_de_imagem(registro):
    return bool(DEPENDE_DE_IMAGEM_RE.search(registro['enunciado'] or ''))


def carregar_registros(path):
    with open(path, encoding='utf-8') as f:
        registros = json.load(f)
    for r in registros:
        r['status'] = 'pendente_revisao' if depende_de_imagem(r) else 'aprovada'
    return registros


def importar(path, concurso=None):
    registros = carregar_registros(path)
    if concurso:
        registros = [r for r in registros if r['concurso'] == concurso]
    if not registros:
        print('nenhum registro para importar')
        return

    flags_imagem = [r for r in registros if r['status'] == 'pendente_revisao']
    if flags_imagem:
        print(f'{len(flags_imagem)} questoes marcadas pendente_revisao por dependerem de imagem/figura ausente:')
        for r in flags_imagem:
            print(f"  - [{r['concurso']}/{r['arquivo_origem']}] {r['enunciado'][:90]}")
        print()

    registros_tabela = [{k: r[k] for k in CAMPOS_TABELA} for r in registros]

    supabase = get_supabase()
    total_inseridas = 0
    total_duplicadas = 0

    for i in range(0, len(registros_tabela), LOTE):
        lote = registros_tabela[i:i + LOTE]
        resultado = (
            supabase.table('questoes')
            .upsert(lote, on_conflict='concurso,hash_conteudo', ignore_duplicates=True)
            .execute()
        )
        inseridas_no_lote = len(resultado.data)
        total_inseridas += inseridas_no_lote
        total_duplicadas += len(lote) - inseridas_no_lote
        print(f'lote {i // LOTE + 1}: {inseridas_no_lote}/{len(lote)} inseridas (resto ja existia)')

    print(f'\n=== TOTAL: {total_inseridas} questoes novas inseridas, '
          f'{total_duplicadas} ja existiam (hash_conteudo duplicado) ===')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arquivo', default=os.path.join(
        os.path.dirname(__file__), '..', 'dados', 'simulados_antigos', 'todas_questoes.json'
    ))
    parser.add_argument('--concurso', default=None)
    args = parser.parse_args()

    if not os.path.exists(args.arquivo):
        print(f'arquivo nao encontrado: {args.arquivo}')
        sys.exit(1)

    importar(args.arquivo, args.concurso)
