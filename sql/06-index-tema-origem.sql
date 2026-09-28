-- =====================================================================
-- Indice pra consulta nova de "questoes ja existentes do mesmo tema" (usada pra pedir
-- variacao de angulo na geracao, geracao/core.py::buscar_enunciados_existentes).
-- O indice existente (questoes_concurso_materia_idx) e PARCIAL, so cobre status='aprovada' -
-- a consulta nova filtra por origem sem filtrar por status (quer ver TODAS as ja geradas
-- daquele tema, pendentes ou nao, pra nao repetir angulo), entao caia fora do indice parcial
-- e virava sequential scan na tabela inteira - causou "statement timeout" real em producao.
-- Rodar este script inteiro no SQL Editor do Supabase.
-- =====================================================================

create index if not exists questoes_concurso_materia_tema_origem_idx
  on questoes (concurso, materia, tema, origem, id desc);
