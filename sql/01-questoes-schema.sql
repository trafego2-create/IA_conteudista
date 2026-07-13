-- =====================================================================
-- APROVA SIM - Banco de questoes central (Supabase / Postgres)
-- Fase 0 do briefing "IA CONTEUDISTA": tabela unica compartilhada por
-- Revisao Farol, Mestre em Questoes/Atualidades e Simulados.
-- Rodar este script inteiro no SQL Editor do Supabase.
-- =====================================================================

create extension if not exists pgcrypto;

create table if not exists questoes (
  id bigserial primary key,

  -- Classificacao para amostragem estratificada e filtros
  concurso text not null,              -- ex.: 'INSS', 'TJSP', 'BB'
  materia text not null,               -- ex.: 'Direito Administrativo'
  tema text,                           -- ex.: 'Sindicancia e PAD' (extraido do material, opcional)

  -- Produto de origem e formato de alternativas
  origem text not null
    check (origem in ('revisao_farol', 'mestre_questoes', 'atualidades', 'simulado_migrado')),
  formato text
    check (formato in ('certo_errado', 'abcde') or formato is null),
    -- null em revisao_farol: nao tem alternativas nem formato de banca

  -- Fluxo de revisao humana (nenhuma questao vai ao aluno sem passar por 'aprovada')
  status text not null default 'pendente_revisao'
    check (status in ('pendente_revisao', 'aprovada', 'rejeitada', 'publicada')),
  revisado_por text,
  revisado_em timestamptz,
  motivo_rejeicao text,

  -- Conteudo da questao
  texto_auxiliar text,                 -- contexto/situacao hipotetica, quando houver
  enunciado text not null,
  alternativas jsonb,                  -- {"A": "...", ..., "E": "..."} quando formato = 'abcde'; null em farol/certo_errado
  gabarito text,                       -- resposta (farol) ou gabarito (mestre_questoes/atualidades)
  comentario text,                     -- fundamentacao com citacao literal de lei; null em farol

  -- Rastreio da fonte, para auditoria e checagem de fidelidade a citacao literal
  arquivo_origem text,                 -- nome do material enviado pela equipe de Produto que gerou a questao
  hash_conteudo text not null,         -- sha256(enunciado) para bloquear duplicata exata na gravacao

  -- Reuso em simulados: cada sorteio grava aqui a data de uso, para excluir
  -- questoes usadas recentemente no mesmo concurso (ver secao de riscos do briefing)
  usada_em timestamptz[] not null default '{}',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint hash_conteudo_unico unique (concurso, hash_conteudo)
);

-- Amostragem estratificada por materia/concurso (Fase 4, ainda nao construida)
create index if not exists questoes_concurso_materia_idx
  on questoes (concurso, materia)
  where status = 'aprovada';

-- Fila de revisao humana (Fase 6)
create index if not exists questoes_status_idx
  on questoes (status);

-- Exclusao de questoes usadas recentemente na amostragem de simulados
create index if not exists questoes_usada_em_idx
  on questoes using gin (usada_em);

-- =====================================================================
-- Notas de uso:
-- - Antes de inserir, calcular hash_conteudo = encode(digest(enunciado, 'sha256'), 'hex')
--   no proprio servico de geracao (Fase 2) para bloquear duplicata exata via
--   a constraint hash_conteudo_unico. Duplicata semantica (parafraseada) nao
--   e coberta por este hash - se isso virar problema na pratica, avaliar
--   checagem adicional depois.
-- - 'gabarito' e generico de proposito: em revisao_farol guarda a resposta
--   do flashcard; em mestre_questoes/atualidades guarda 'CERTO'/'ERRADO' ou
--   a letra correta.
-- - Nenhuma linha deve ser servida ao aluno com status != 'aprovada'
--   (e simulados_migrados entram direto como 'aprovada', pois ja foram
--   usados/revisados quando eram simulados antigos).
-- =====================================================================
