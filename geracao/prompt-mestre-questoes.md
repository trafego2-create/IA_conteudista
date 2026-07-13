# Geração de questão — Mestre em Questões / Atualidades

Resolve o furo de arquitetura levantado sobre a citação literal de lei: em vez de
confiar em instrução de prompt ("copie literalmente"), a citação só pode vir do
`trecho` já extraído deterministicamente pelo parser (Fase 1) do `material_fonte`.
A validação (Fase 3) confere por substring, não por outra chamada de LLM opinando
sobre o próprio texto gerado.

## System prompt

```
Você é um conteudista especializado em concursos públicos, escrevendo questões
comentadas no padrão da plataforma Aprova Sim, com o mesmo nível de profundidade
jurídica e didática do material de referência.

REGRAS OBRIGATÓRIAS:
1. Use apenas o TRECHO fornecido como fonte de conteúdo. Nunca cite lei, decreto,
   artigo ou instrução normativa que não apareça literalmente no TRECHO.
2. Qualquer citação legal no campo "comentario" deve ser uma transcrição literal
   de um trecho do TRECHO fornecido, delimitada entre aspas retas (" ").
   Não parafraseie o texto legal citado.
3. Gere só um objeto JSON no formato de saída abaixo, sem texto fora do JSON.

FORMATO DE SAÍDA (JSON):
{
  "enunciado": "...",
  "gabarito": "CERTO" ou "ERRADO",
  "comentario": "..."
}
```

## User prompt (template)

```
CONCURSO: {concurso}
MATÉRIA: {materia}
TEMA: {tema}
FORMATO: certo_errado

TRECHO (fonte de verdade, não usar nada fora daqui):
"""
{trecho}
"""

Gere 1 questão comentada no formato certo_errado sobre este trecho.
```

## Exemplo real preenchido (para testar agora no ChatGPT ou na API)

Usei o trecho de `SEGURIDADE SOCIAL / REGIMES PRÓPRIOS DE PREVIDÊNCIA SOCIAL`,
extraído de verdade da apostila específica (página 278) pelo parser da Fase 1:

```
CONCURSO: INSS
MATÉRIA: SEGURIDADE SOCIAL
TEMA: REGIMES PRÓPRIOS DE PREVIDÊNCIA SOCIAL
FORMATO: certo_errado

TRECHO (fonte de verdade, não usar nada fora daqui):
"""
Regimes Próprios de Previdência Social RPPS na CF/88 - Parte 1 CF/88. Art. 40.
O regime próprio de previdência social dos servidores titulares de cargos
efetivos terá caráter contributivo e solidário, mediante contribuição do
respectivo ente federativo, de servidores ativos, de aposentados e de
pensionistas, observados critérios que preservem o equilíbrio financeiro e
atuarial. Caráter contributivo: servidores ativos, aposentados e pensionistas
contribuem por meio de tributos. Caráter solidário: há uma tributação conforme
a capacidade economia. DA APOSENTADORIA DO SERVIDOR PÚBLICO § 1º. O servidor
abrangido por regime próprio de previdência social será aposentado: I - por
incapacidade permanente para o trabalho, no cargo em que estiver investido,
quando insuscetível de readaptação, hipótese em que será obrigatória a
realização de avaliações periódicas para verificação da continuidade das
condições que ensejaram a concessão da aposentadoria, na forma de lei do
respectivo ente federativo; II - compulsoriamente, com proventos proporcionais
ao tempo de contribuição, aos 70 (setenta) anos de idade, ou aos 75 (setenta e
cinco) anos de idade, na forma de lei complementar...
"""

Gere 1 questão comentada no formato certo_errado sobre este trecho.
```

Cole os dois blocos (system + user) no ChatGPT (ou chame a API da OpenAI com esse
system/user, usando `response_format={"type": "json_object"}` pra garantir saída
em JSON) para já ter uma questão real gerada pra reunião.

## Validação determinística (Fase 3) — resolve os furos 1 e 2

Não usa outra chamada de LLM como juiz. Extrai a citação entre aspas do
`comentario` gerado e confere se ela é uma substring literal do `trecho`
(normalizando espaços/maiúsculas, já que a LLM pode reformatar espaçamento).
Se a citação não bater, a questão não passa nem para "pendente_revisao" — vai
direto para "rejeitada" automaticamente, sem gastar revisão humana com algo que
já sabemos que alucinou.

```python
import re

def validar_citacao(comentario: str, trecho: str) -> bool:
    citacoes = re.findall(r'"([^"]+)"', comentario)
    if not citacoes:
        return False  # comentario sem nenhuma citacao entre aspas falha a regra 2
    trecho_norm = re.sub(r'\s+', ' ', trecho).upper()
    for citacao in citacoes:
        citacao_norm = re.sub(r'\s+', ' ', citacao).strip().upper()
        if citacao_norm not in trecho_norm:
            return False
    return True
```

Isso não garante que o **gabarito** (CERTO/ERRADO) esteja semanticamente
correto — só garante que qualquer citação legal invocada existe de fato no
material-fonte, palavra por palavra. A corretude do gabarito em si ainda
depende da revisão humana (Fase 6), o que é consistente com o que o próprio
briefing já assume ("toda questão gerada permanece pendente de revisão").
