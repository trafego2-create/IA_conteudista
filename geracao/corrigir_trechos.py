"""Corrige trechos de material_fonte cortados no lugar errado (ver preferir_titulo_exato em
parser/parse_apostila.py): atualiza IN PLACE, por id, as linhas cujo hash mudou apos reprocessar
as apostilas. Salva backup dos trechos antigos antes de qualquer update."""
import json
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import get_supabase  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), '..', 'dados')
NOVOS = os.path.join(BASE, 'material_fonte_onedrive', 'todos_registros.json')
BACKUP = os.path.join(BASE, 'material_fonte_backup_antes_correcao.json')


def main():
    novos = json.load(open(NOVOS, encoding='utf-8'))
    supabase = get_supabase()

    rows, off = [], 0
    while True:
        r = supabase.table('material_fonte').select('*').range(off, off + 999).execute()
        rows += r.data
        if len(r.data) < 1000:
            break
        off += 1000
    db = {(x['concurso'], x['arquivo_origem'], x['materia'], x['tema']): x for x in rows}

    mudancas = []
    for n in novos:
        o = db.get((n['concurso'], n['arquivo_origem'], n['materia'], n['tema']))
        if o and o['hash_conteudo'] != n['hash_conteudo'] and n['trecho'].strip():
            mudancas.append((o, n))

    with open(BACKUP, 'w', encoding='utf-8') as f:
        json.dump([o for o, _ in mudancas], f, ensure_ascii=False)
    print(f'{len(mudancas)} linhas a corrigir; backup em {BACKUP}')

    for o, n in mudancas:
        supabase.table('material_fonte').update({
            'trecho': n['trecho'], 'hash_conteudo': n['hash_conteudo'],
            'pagina': n['pagina'], 'ordem': n['ordem'],
        }).eq('id', o['id']).execute()
    print('ok')


if __name__ == '__main__':
    main()
