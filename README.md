# Aprova Sim — IA Conteudista (piloto INSS)

Protótipo do banco de questões central descrito no `BRIEFING - IA CONTEUDISTA`.

## Setup

1. `pip install -r requirements.txt`
2. Copie `.env.example` para `.env` e preencha (não commitar `.env`):
   - `OPENAI_API_KEY` — chave da API da OpenAI.
   - `SUPABASE_URL` / `SUPABASE_KEY` — em Settings > API no painel do Supabase (use a chave `anon` ou uma role restrita, não a `service_role` a menos que necessário).

## Estrutura

- `sql/01-questoes-schema.sql` — Fase 0: tabela central de questões (rodar primeiro no Supabase).
- `sql/02-material-fonte-schema.sql` — Fase 1: tabela do material parseado (rodar depois da 01).
- `sql/03-alter-formato-nullable.sql` — migração pontual: `formato` precisa aceitar null
  (Revisão Farol não tem formato de alternativas). Rodar se a tabela `questoes` já existia
  antes dessa correção.
- `parser/parse_apostila.py` — Fase 1: extrai matéria/tema/trecho/página de uma apostila PDF.
  Uso: `python parse_apostila.py <caminho_pdf> <concurso> <arquivo_origem> <saida.json>`
- `geracao/gerar_questao.py` — Fase 2 + 3: puxa um trecho do `material_fonte`, gera 1 questão
  via OpenAI (`--model` padrão `gpt-4.1`) e grava em `questoes`, com validação determinística
  da citação legal (substring literal do trecho, não outra LLM como juiz).
  Suporta dois produtos via `--produto`:
  - `mestre_questoes` (padrão): certo_errado, citação obrigatória.
    `python gerar_questao.py --materia "SEGURIDADE SOCIAL" --tema "REGIMES PRÓPRIOS DE PREVIDÊNCIA SOCIAL"`
  - `revisao_farol`: enunciado+resposta (flashcard), citação opcional mas se houver tem
    que ser literal também.
    `python gerar_questao.py --produto revisao_farol --materia "DIREITO ADMINISTRATIVO" --tema "LEI Nº 9.784/99"`
- `geracao/prompt-mestre-questoes.md` / `geracao/prompt-revisao-farol.md` — os mesmos prompts
  usados pelo script, em formato legível, pra testar manualmente no ChatGPT sem rodar código.

## Limitações conhecidas (ver furos de arquitetura levantados sobre o briefing)

- Cobre Mestre em Questões/Atualidades (certo_errado) e Revisão Farol, só concurso INSS.
  Formato ABCDE (TJSP/BB) ainda não tem material-fonte pra testar.
- Validação de citação garante fidelidade da citação legal, não a corretude semântica
  do gabarito — isso ainda depende de revisão humana (Fase 6, não construída).
- Parser é heurístico (baseado em divisores de página + sumário); pode não generalizar
  para apostilas com diagramação muito diferente das 2 já testadas, nem cobre docx/pptx
  ainda (o briefing pede os 3 formatos).
- Fases 4 (sorteio de simulados), 5 (migração de simulados antigos) e 6 (revisão humana)
  ainda não foram construídas.
