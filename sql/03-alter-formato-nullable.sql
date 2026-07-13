-- Corrige o schema da Fase 0: Revisao Farol nao tem formato de alternativas
-- (nao e certo_errado nem abcde, e so enunciado+resposta), entao 'formato'
-- precisa aceitar null. Rodar isso na tabela `questoes` ja existente.

alter table questoes alter column formato drop not null;

alter table questoes drop constraint if exists questoes_formato_check;
alter table questoes add constraint questoes_formato_check
  check (formato in ('certo_errado', 'abcde') or formato is null);
