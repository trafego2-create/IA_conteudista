-- =====================================================================
-- APROVA SIM - Novo valor de origem: 'banco_real'
-- Questoes extraidas do material "MQ DIGITAL"/"MQE DIGITAL" (Downloads/
-- Apostilas Base de Conteudo): questoes reais de banca ja comentadas por
-- humano, nao geradas pela IA. Diferem de 'mestre_questoes' (gerada por IA)
-- e 'simulado_migrado' (reaproveitamento de simulado antigo da propria
-- plataforma) - sao conteudo de terceiros usado como fonte, precisam do
-- mesmo fluxo de revisao humana antes de virar 'aprovada'.
-- =====================================================================

alter table questoes drop constraint if exists questoes_origem_check;

alter table questoes add constraint questoes_origem_check
  check (origem in ('revisao_farol', 'mestre_questoes', 'atualidades', 'simulado_migrado', 'banco_real'));

-- banca e ano da prova de origem (ex.: 'CESPE-CEBRASPE/2021'), texto livre
-- tal como extraido do PDF - so populado em origem = 'banco_real'.
alter table questoes add column if not exists banca_ano text;

-- =====================================================================
-- Notas de uso:
-- - formato/alternativas/gabarito/comentario seguem as mesmas regras de
--   mestre_questoes (certo_errado ou abcde, nunca null).
-- - status inicial continua 'pendente_revisao' - mesmo sendo conteudo
--   curado por terceiro (nao gerado por IA), a regra de negocio do
--   briefing e nenhuma questao ir ao aluno sem revisao humana explicita.
-- - a citacao literal de lei no comentario NAO passa pela validacao
--   automatica (validar_citacao) porque nao ha um 'trecho' de
--   material_fonte associado 1:1 a essas questoes - a fidedignidade e do
--   proprio curso de origem, e cabe a revisao humana confirmar.
-- =====================================================================
