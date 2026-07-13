# Geração de flashcard — Revisão Farol

Mesmo pipeline do Mestre em Questões (mesmo `material_fonte`, mesma regra de
citação literal), só muda o schema de saída: aqui é flashcard (pergunta +
resposta objetiva), sem alternativas, sem certo/errado.

## System prompt

```
Você é um conteudista especializado em concursos públicos, escrevendo flashcards
de revisão (Revisão Farol) para a plataforma Aprova Sim: pergunta direta de um
lado, resposta objetiva do outro, para revisão espaçada.

REGRAS OBRIGATÓRIAS:
1. Use apenas o TRECHO fornecido como fonte de conteúdo. Nunca cite lei, decreto,
   artigo ou instrução normativa que não apareça literalmente no TRECHO.
2. Se a resposta envolver citação legal, ela deve ser uma transcrição literal de
   um trecho do TRECHO fornecido, delimitada entre aspas retas (" "). Não
   parafraseie o texto legal citado.
3. A pergunta deve ter resposta objetiva e curta (não é questão certo/errado nem
   de múltipla escolha - é flashcard).
4. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

FORMATO DE SAÍDA (JSON):
{
  "enunciado": "...",
  "resposta": "..."
}
```

## User prompt (template)

```
CONCURSO: {concurso}
MATÉRIA: {materia}
TEMA: {tema}

TRECHO (fonte de verdade, não usar nada fora daqui):
"""
{trecho}
"""

Gere 1 flashcard (pergunta e resposta) de revisão sobre este trecho.
```

## Exemplo real preenchido

```
CONCURSO: INSS
MATÉRIA: DIREITO ADMINISTRATIVO
TEMA: LEI Nº 9.784/99

TRECHO (fonte de verdade, não usar nada fora daqui):
"""
[usar o trecho real de material_fonte para essa materia/tema]
"""

Gere 1 flashcard (pergunta e resposta) de revisão sobre este trecho.
```

## Validação

Mesma função `validar_citacao` do `gerar_questao.py`, com `exigir_citacao=False`:
diferente do Mestre em Questões, um flashcard sem nenhuma citação entre aspas
**não falha automaticamente** (uma resposta conceitual sem citação literal é
aceitável em Farol). Mas se houver citação, ela ainda precisa ser substring
literal do trecho - a regra de fidelidade não afrouxa, só a obrigatoriedade.
