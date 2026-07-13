-- =====================================================================
-- APROVA SIM - Material-fonte parseado (Supabase / Postgres)
-- Complementa o schema de questoes (aprovasim-questoes-schema.sql).
-- Guarda o resultado do parser da Fase 1 (materia/tema/trecho extraidos
-- das apostilas), reaproveitavel entre lotes e produtos, sem reprocessar
-- o PDF/DOCX/PPTX original a cada geracao.
-- Rodar este script inteiro no SQL Editor do Supabase.
-- =====================================================================

create table if not exists material_fonte (
  id bigserial primary key,

  concurso text not null,              -- ex.: 'INSS'
  arquivo_origem text not null,        -- ex.: 'inss-esquematizada-especificas-plataforma.pdf'
  materia text not null,               -- ex.: 'SEGURIDADE SOCIAL'
  tema text not null,                  -- ex.: 'REGIMES PRÓPRIOS DE PREVIDÊNCIA SOCIAL'
  ordem int not null,                  -- posicao do tema dentro da materia, na ordem do sumario/documento
  pagina int,                          -- pagina impressa onde o tema comeca no arquivo de origem

  trecho text not null,                -- texto literal extraido, usado como fonte de verdade na geracao
  hash_conteudo text not null,         -- sha256(trecho), para reprocessar um arquivo sem duplicar

  created_at timestamptz not null default now(),

  constraint material_fonte_unico unique (concurso, arquivo_origem, hash_conteudo)
);

-- consulta principal do servico de geracao: puxar o trecho de um tema
-- especifico de um concurso, sem reler o arquivo original
create index if not exists material_fonte_concurso_materia_tema_idx
  on material_fonte (concurso, materia, tema);

-- =====================================================================
-- Notas de uso:
-- - Uma linha por tema (nao por pagina) - o parser da Fase 1 ja agrupa o
--   conteudo de varias paginas em um unico trecho por tema, usando o
--   sumario de cada materia como fonte de verdade da divisao.
-- - 'ordem' existe para reconstruir a sequencia original do documento
--   quando for preciso (ex.: gerar um resumo materia por materia).
-- - Reprocessar o mesmo arquivo (ex.: apostila atualizada) so gera
--   duplicata se o trecho mudar; conteudo identico e bloqueado pelo
--   'material_fonte_unico'. Se a apostila for atualizada, o ideal e criar
--   uma nova versao de arquivo_origem (ex.: sufixo de data) e revisar as
--   questoes da tabela `questoes` que citam o trecho antigo.
-- =====================================================================
