"""Corrige o campo 'alternativas' de questoes ja importadas (formato abcde), sem tocar em
status/revisado_por/revisado_em - so reparsing (com o fix de opcoes multi-linha) e sobrescrita
pontual do campo. hash_conteudo e baseado so no enunciado, que nao mudou, entao serve de chave
estavel pra achar a linha certa sem duplicar nem depender de id."""
import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import get_supabase  # noqa: E402


def carregar_abcde(path):
    with open(path, encoding='utf-8') as f:
        registros = json.load(f)
    return [r for r in registros if r['formato'] == 'abcde']


def corrigir(path):
    registros = carregar_abcde(path)
    if not registros:
        print('nenhum registro abcde para corrigir')
        return

    supabase = get_supabase()
    atualizados = 0
    nao_encontrados = 0

    for r in registros:
        resultado = (
            supabase.table('questoes')
            .update({'alternativas': r['alternativas']})
            .eq('concurso', r['concurso'])
            .eq('hash_conteudo', r['hash_conteudo'])
            .execute()
        )
        if resultado.data:
            atualizados += 1
        else:
            nao_encontrados += 1

    print(f'\n=== TOTAL: {atualizados} atualizadas, {nao_encontrados} nao encontradas no banco (normal se ainda nao importadas) ===')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arquivo', default=os.path.join(
        os.path.dirname(__file__), '..', 'dados', 'mq_digital', 'todas_questoes.json'
    ))
    args = parser.parse_args()

    if not os.path.exists(args.arquivo):
        print(f'arquivo nao encontrado: {args.arquivo}')
        sys.exit(1)

    corrigir(args.arquivo)
