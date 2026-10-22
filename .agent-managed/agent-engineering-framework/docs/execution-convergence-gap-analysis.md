# Execution Convergence Gap Analysis

**Status:** auditado e implementado no worktree; a validação local está registrada
na seção final. Nenhuma mudança deste conjunto foi consolidada em commit.

**Escopo auditado:** `core/`, `skills/engineering-protocol/`, `agents/`,
`state/`, `profiles/`, `harness/`, `workflows/`, `templates/`,
`bin/agent-kit` e `tests/`.

**Evidência de baseline:** a suíte atual passou com 29 testes; o validador do
framework passou. O checkout contém mudanças pré-existentes e não consolidadas,
inclusive o runtime de state V2, adapters de quatro harnesses, roteamento de
modelos, PATH opcional e guia de uso. Esta análise as trata como o estado atual
do código, sem atribuí-las a esta melhoria.

## Veredito

O framework já tem a maior parte das fronteiras certas: autoridade do
Orchestrator, roles separados, Reviewer read-only, QA não mutante,
`EXTERNAL_DIRTY_WORKTREE`, estado portátil, cápsula de contexto, classificação
de risco e um limite de reentrada em review. Ele não possui, porém, um contrato
executável de **Developer Closure** nem recibos de gate que permitam decidir se
uma nova execução é necessária.

O ciclo excessivo é possível porque uma evidência de gate é apenas o último
registro textual de um nome de gate. Não é vinculada à tarefa, ao papel que o
executou, ao escopo/fonte avaliada, nem a uma assinatura da falha. A política
fala em limitar loops, mas o runtime não conta tentativas de gate, não detecta
ausência de progresso e não incrementa as iterações de review. Assim, o
Orchestrator não tem fatos suficientes para recusar uma repetição idêntica.

## Mapa atual

```text
core/orchestration.md       decisão, risco, custos, escalonamento genérico
core/verification.md        gates, Reviewer/Verifier, evidência externa
core/delegation.md          fronteiras de mutação dos papéis
profiles/*.md               descoberta tecnológica; comandos continuam locais
workflows/*.md              composição fina e sequência de alto nível
state/state.py              estado V1/V2, gates, handoff, validação e close
state/routing.py            tarefas, classificação, readiness e métricas
state/activity.py           proposta, plano, cápsula e recibos de dispatch
bin/agent-kit               geração/permite adapters e superfície CLI
```

Não há uma segunda state machine hoje. `phase`, `tasks.<id>.status`,
`reviewIteration`, `executionPolicy`, `gates`, `handoff` e `metrics` são a fonte
portátil já existente.

## Matriz de capacidades

| Capability | Existing | Partial | Missing | Current owner | Recommended change |
|---|---:|---:|---:|---|---|
| Developer lint |  | ✓ |  | profiles + adapters | Permitir ao Developer executar gates descobertos; manter comando no projeto/profile. |
| Developer analyze |  | ✓ |  | profiles + adapters | Mesmo contrato de gate sem hardcode tecnológico. |
| Developer focused tests |  | ✓ |  | profiles + project rules | Tornar `focused-tests` uma classe de gate declarada pela tarefa/projeto. |
| Developer closure |  |  | ✓ | state + verification | Registrar uma closure verificável antes de `reviewing`. |
| Review severity |  | ✓ |  | workflow review | Formalizar `BLOCKER`/`MAJOR`/`MINOR`; aceitar nomes históricos como aliases de entrada. |
| Review batch |  | ✓ |  | reviewer + orchestrator | Exigir um conjunto completo de findings por rodada e uma única devolução ao Developer. |
| Review retry budget |  | ✓ |  | state executionPolicy | Reutilizar `maxReviewIterations`; incrementar/aplicar automaticamente por tarefa. |
| Gate deduplication |  |  | ✓ | state gate runtime | Persistir fingerprint de fonte+gate e reutilizar PASS ou impedir FAIL idêntico. |
| No-progress detection |  |  | ✓ | state + orchestration | Comparar fonte, gate e assinatura de falha; escalar em vez de repetir. |
| Failure fingerprint |  |  | ✓ | state gate runtime | Derivar hash de evidência compacta, sem persistir saída bruta adicional. |
| Source fingerprint |  |  | ✓ | state/activity boundary | Produzir hash de escopo da tarefa; sem boundary verificável, não deduplicar. |
| BLOCKED escalation | ✓ | ✓ |  | state + orchestration | Reusar `blocked`/`human_escalation`; incluir razão estruturada de convergência. |
| Human intervention | ✓ |  |  | state + workflows | Tornar o motivo e a opção de operador explícitos na convergência. |
| Final gate contract | ✓ | ✓ |  | state close + verification | Conservar `full`, `protocol`, `reviewer`, `qa`; acrescentar closure somente quando requerida. |

## Auditoria por papel

### Developer

`core/verification.md` já diz que Implementers executam gates direcionados e os
profiles já orientam a descobrir formatter, análise e testes a partir do
projeto. O manifesto tem apenas flags globais de verificação; não existe um
catálogo de classes de gate nem uma closure do Developer.

As permissões divergem por harness:

- OpenCode gera Developer com escrita no escopo de código, mas nega todo
  `bash` e a própria instrução diz para não usar shell. Isto impede format,
  analyze e testes pelo papel que deveria prová-los.
- Codex gera Developer com `workspace-write`; Copilot oferece `execute`; Claude
  oferece `Bash`. Estes três podem executar comandos, mas não compartilham um
  contrato de evidência de gate.
- OpenCode QA possui allow-list não mutante por profile. O formatter é somente
  checado, não aplicado. Copilot QA não recebe `execute` e Claude QA não recebe
  `Bash`, portanto a capacidade de QA também não é uniforme.

Conclusão: há orientação de validação, mas não existe **Developer validation**
aplicável de ponta a ponta nem `READY_FOR_REVIEW` baseado em fatos.

### Reviewer

Reviewer é corretamente independente e read-only nos adapters e no core. O
workflow já pede findings priorizados e com evidência, mas usa
`CRITICAL/HIGH/MEDIUM/LOW` apenas como texto. Não há schema de finding, lote,
severidade persistida ou regra que diferencie observação menor de retorno
obrigatório ao Developer.

`reviewIteration` e `maxReviewIterations` já existem no state V2 e a gravação
recusa entrar novamente em review quando o contador já atingiu o limite. Mas o
runtime não incrementa o contador nem registra uma rodada/finding; alguém teria
de editar o estado manualmente. O mecanismo é uma trava parcial, não um budget
de convergência funcional.

### QA / Verifier

QA é não mutante e deve devolver evidência ao Orchestrator. A classificação
`EXTERNAL_DIRTY_WORKTREE` está corretamente preservada: um erro fora da
fronteira da tarefa não vira defeito dela. Quota, rate limit e modelo
indisponível também já são circuit breakers separados e não devem consumir
budget de convergência.

Falta classificar de forma estruturada um FAIL de gate como defeito da tarefa,
baseline conhecida, ambiente/ferramenta indisponível ou externo antes de abrir
uma nova implementação. Não há deduplicação de gate nem limite de mesma falha.

### Orchestrator

O core já preserva tarefas simples como single-agent e removeu corretamente o
limite artificial de `steps`. Contudo, `state/activity.py` sempre inclui
Reviewer **e QA** em um plano de `continue`/`feature`, inclusive para risco LOW;
isso contradiz o fast path pretendido. A política de risco também declara
`qa-basic` para LOW. QA deve ser selecionado apenas quando o risco, a tarefa, o
projeto ou a aceitação o exigirem.

Há `attempts`, métricas genéricas, recibos de dispatch e uma frase para limitar
loops, mas nenhum deles controla tentativas de gate/review, mede progresso de
código ou aplica bloqueio por repetição. Métricas atuais servem a roteamento de
modelo e consumo, não à convergência.

### State e gates

O state V2 já preserva compatibilidade com V1, possui `phase` suficiente
(`implementing`, `gates`, `reviewing`, `fixing`, `qa`, `blocked` e
`human_escalation`) e não deve receber uma state machine paralela.

O mapa `gates` guarda apenas o último `{result, command, evidence, at}` para
cada nome. Ele não tem tarefa, role, classe de gate, escopo, fonte,
fingerprint, assinatura de falha, motivo de reexecução ou relação com uma
closure. `attempts` não recebe validação semântica e `metrics` só aceita
contadores escalares. Portanto nenhum campo existente resolve de forma segura
dedupe/no-progress; será necessário estender o recibo de gate no owner atual,
com migração compatível.

## KEEP / EXTEND / REFACTOR / REMOVE / ADD

### KEEP

- Uma única fonte portátil em `.specs/features/<feature>/state.json`.
- `phase` e status V2 existentes; `blocked` e `human_escalation` já expressam a
  saída necessária.
- Separação Developer mutante, Reviewer independente/read-only e QA não
  mutante.
- Classificação de risco, roteamento por provider, circuit breaker de provider,
  `ContextCapsule`, `DispatchReceipt`, `EXTERNAL_DIRTY_WORKTREE` e ausência de
  `steps` no Orchestrator.
- Profiles como descoberta tecnológica e project rules como autoridade de
  comandos reais.

### EXTEND

- `executionPolicy` com budget de review, acrescentando limites de falha de
  gate e falta de progresso no mesmo owner.
- Recibo de `gates` com fatos de fonte/escopo/role e assinatura de falha.
- `ContextCapsule` com closure do Developer, gates requeridos e paths alterados.
- `metrics` com somente contadores factuais de convergência.
- Workflows como clientes finos da política, sem copiar regras.

### REFACTOR

- Geração de permissões dos adapters para que Developer possa rodar gates
  aprovados e QA possa executar apenas verificação não mutante equivalente em
  todos os harnesses que a suportem.
- Seleção de papéis no plano para deixar QA fora do fast path LOW quando não
  for exigido.
- Linguagem de Reviewer para retornar lote completo e severidade normalizada.

### REMOVE

- A proibição absoluta de shell do Developer OpenCode e as instruções que a
  reforçam.
- A suposição implícita de que presença de um papel QA exige despacho em toda
  tarefa.

### ADD

- Um contrato canônico de closure, recibo de gate e decisão de convergência no
  runtime de state; não uma nova state machine.
- Testes de dedupe PASS/FAIL, mudança relevante de fonte, lote de review,
  severidades, budget/escalonamento, falhas externas, cross-harness e cenário
  Flutter descrito no pedido.

## Desenho mínimo recomendado

O owner deve permanecer dividido entre `core/orchestration.md` (decidir
reentrada/budget), `core/verification.md` (closure e validade de gates),
`core/delegation.md` (autoridade dos papéis) e `state/` (contrato executável).
Não é necessário criar um novo documento core nem uma state machine.

1. Adicionar a `executionPolicy` apenas os budgets semânticos
   `maxSameGateFailure` e `maxNoProgressRounds`, preservando
   `maxReviewIterations`. Defaults ficam na policy compartilhada e podem ser
   sobrescritos no bloco **Execution Policy** de `tasks.md`; não no profile.
2. Evoluir cada registro de `gates` para um `GateReceipt` compatível: tarefa,
   executor, classe conceitual (`format`, `static-analysis`, `lint`,
   `focused-tests`, `required-tests`, `build`), escopo, source fingerprint e,
   para FAIL, failure signature. Campos antigos continuam legíveis como
   evidência sem fingerprint e nunca são reutilizados automaticamente.
3. Reutilizar `tasks.<id>.reviewIteration` e acrescentar um pequeno bloco de
   convergência no próprio estado da tarefa, não no root: closure atual,
   contadores e último stop. A closure referencia gate IDs; não copia command
   ou output.
4. Permitir `reviewing` somente se os gate classes requeridos pela tarefa têm
   recibos PASS/SKIP para a mesma fonte. `SKIP` exige razão compacta de
   não-aplicabilidade. Isso é validação técnica, não autoaprovação de review.
5. Antes de executar um gate, calcular seu fingerprint por escopo da tarefa e
   classe/command. PASS idêntico é reutilizado quando a política permite; FAIL
   com mesma assinatura não é repetido automaticamente. Fonte alterada permite
   nova tentativa. Se não houver fronteira verificável, executar normalmente e
   nunca deduplicar por suposição.
6. Um retorno de Reviewer deve conter um único lote. `BLOCKER` e `MAJOR`
   reabrem Developer uma vez por rodada; `MINOR` é registrado sem reabertura
   automática. Os nomes atuais `CRITICAL/HIGH/MEDIUM/LOW` ficam aceitos apenas
   como aliases para não quebrar adapters/projetos existentes.
7. Ao atingir budget ou não haver progresso, manter a tarefa em `blocked` e a
   feature em `human_escalation`, com causa factual e opções no handoff. Falhas
   externas/provider não incrementam esses contadores.
8. Derivar se QA é exigido de `riskVerification`, metadados/gates da tarefa ou
   regra de projeto. Para LOW sem exigência, o plano contém Developer e
   Reviewer, preservando o fast path.

Este desenho adiciona fatos portáveis mínimos e usa as transições existentes.
Ele não introduz Flutter no core, não duplica comandos, não persiste sessões ou
transcritos, e não usa timeout/`steps` como mecanismo de conclusão.

## Resultado da execução

O runtime agora aplica o desenho acima no estado V2: `Developer Closure`,
`GateReceipt` com task/papel/classe/escopo/source fingerprint, deduplicação de
PASS, bloqueio de falta de progresso, budget de review, lote normalizado de
findings e classificação `EXTERNAL` sem consumo de budget. O fingerprint de
decisão do Developer também inclui seu papel, para que um recibo de QA nunca
seja reutilizado como se fosse validação do Developer.

O roteamento deixa QA fora de tarefas LOW quando nenhuma regra o exige, mantém
Reviewer e QA não mutantes, e carrega a closure no `ContextCapsule` portátil.
Adapters, profiles e guia de uso foram atualizados sem definir comandos de
Flutter/Laravel/Kotlin no core. A migração V2 preenche os novos campos; V1 e
recibos legados continuam legíveis e não são deduplicados por suposição.

## Riscos de implementação a controlar

- Um fingerprint de repositório inteiro trataria trabalho alheio como mudança
  relevante; dedupe só pode ocorrer com boundary da tarefa comprovada.
- `format` do Developer é mutante e deve invalidar gates posteriores quando
  modificar arquivos; QA e Reviewer continuam sem formatar.
- Configurar `bash: allow` indiscriminadamente abriria execução fora de gates;
  adapters devem oferecer a menor permissão praticável e project rules ainda
  escolhem comandos.
- Estado V1 e gates legados devem validar/migrar. Como eles não possuem
  fingerprints, devem executar uma vez em vez de reutilizar evidência fraca.
- A mudança de obrigatoriedade de QA altera apenas seleção por padrão; uma regra
  de projeto ou gate explícito sempre pode exigi-lo.
