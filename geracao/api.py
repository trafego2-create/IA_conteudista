import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core import PRODUTOS, MaterialNaoEncontrado, ProdutoInvalido, gerar_questao  # noqa: E402

app = FastAPI(title='Aprova Sim - IA Conteudista')


class GerarRequest(BaseModel):
    materia: str
    tema: str
    produto: str = 'mestre_questoes'
    model: str = 'gpt-4.1'


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/gerar')
def gerar(req: GerarRequest):
    try:
        return gerar_questao(req.materia, req.tema, req.produto, req.model)
    except MaterialNaoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProdutoInvalido as e:
        raise HTTPException(status_code=400, detail=str(e))
