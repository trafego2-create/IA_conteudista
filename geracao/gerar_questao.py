import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import PRODUTOS, MaterialNaoEncontrado, gerar_questao  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--produto', choices=list(PRODUTOS), default='mestre_questoes')
    parser.add_argument('--materia', required=True)
    parser.add_argument('--tema', required=True)
    parser.add_argument('--model', default='gpt-4.1')
    args = parser.parse_args()

    try:
        resultado = gerar_questao(args.materia, args.tema, args.produto, args.model)
    except MaterialNaoEncontrado as e:
        print(str(e))
        sys.exit(1)

    print(f'\nValidação de citação: {"PASSOU" if resultado["citacao_validada"] else "FALHOU"}')
    print(f'Status gravado: {resultado["status"]}')
    print(f'Questão inserida com id: {resultado["id"]}')
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
