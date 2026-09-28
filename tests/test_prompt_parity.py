"""
Compara o prompt carregado contra uma cópia fixa do `SYSTEM_PROMPT` do Kotlin
(`OpenAiVereditoLlmClient.kt`, linhas 27-36 no momento em que este arquivo foi escrito)
— evita que os dois divirjam silenciosamente se alguém editar um lado só
(fase-1-criterios.md, critério de aceite "prompt idêntico"). Comparação ignora espaço
em branco de borda (`.strip()`) — a Kotlin raw string tem quebra de linha logo após
`\"\"\"` que não carrega significado nenhum pro modelo.
"""

from app.agents.evaluator import load_system_prompt

KOTLIN_SYSTEM_PROMPT = """
Você avalia uma simulação de entrevista de emprego em português do Brasil. Analise o
transcript da tentativa atual e produza um veredito estruturado: nota_geral (0 a 10, pode
ter uma casa decimal), pontos_fortes (lista de strings curtas), pontos_fracos (lista de
strings curtas), feedback_texto (parágrafo único, direto, construtivo).

Se houver histórico de tentativas anteriores do mesmo Ensaio (nota e feedback anteriores),
leve em conta a evolução: aponte explicitamente se um ponto fraco de uma tentativa anterior
se repete ou foi corrigido nesta.
"""


def test_prompt_do_avaliador_e_identico_ao_prompt_do_kotlin():
    assert load_system_prompt() == KOTLIN_SYSTEM_PROMPT.strip()
