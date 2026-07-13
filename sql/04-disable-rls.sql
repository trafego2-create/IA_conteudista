-- As tabelas material_fonte e questoes vieram com Row Level Security ativado
-- (padrao de seguranca de projetos novos do Supabase) e sem nenhuma politica
-- de acesso, entao a API (chave publishable) via PostgREST retorna sempre
-- vazio, mesmo com dados existentes - sem erro, so filtra tudo silenciosamente.
--
-- Essa e uma ferramenta interna (script Python rodado localmente pela equipe),
-- nao um app publico com usuarios finais, entao nao precisamos de politica por
-- linha/usuario. Mais simples e correto pra esse caso e so desativar RLS.

alter table material_fonte disable row level security;
alter table questoes disable row level security;
