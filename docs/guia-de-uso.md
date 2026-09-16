# Guia de uso do Agent Engineering Framework

Este guia parte de uma regra simples: execute os comandos na raiz do projeto
consumidor. O framework mantém política e adapters gerenciados. O projeto
continua dono do código, regras, `.specs`, evidências e `.ai-memory.toml`.

## 1. Conceitos rápidos

- **Harness** é o ambiente que executa os agentes: `opencode`, `codex`,
  `copilot` ou `claude`.
- **Provider** é o provedor usado na atividade. Um provider explícito é
  estrito. `auto` permite escolher entre os providers aprovados no catálogo.
- **Modelo** é escolhido por papel: Orchestrator, Developer, Reviewer e QA.
- **Profile** adiciona orientação tecnológica: `generic`, `flutter`, `laravel`
  ou `kotlin-multiplatform`.
- A ordem de `--harness` importa. O primeiro é o harness de controle e define o
  modelo persistente do Orchestrator.

## 2. Primeiro uso e acesso global ao `agent-kit`

Na primeira execução, use o caminho absoluto do binário:

```bash
cd /caminho/do/meu-projeto
/caminho/para/agent-engineering-framework/bin/agent-kit init \
  --profile generic \
  --harness opencode \
  --harness codex
```

Em terminal interativo, o `init` pode perguntar pela identidade do ai-memory e
depois mostra uma pergunta separada:

```text
ai-memory workspace [minha-organizacao]:
ai-memory project [meu-projeto]:
Adicionar agent-kit ao PATH em /Users/me/.zshrc? [y/N]:
```

Responda `y` ou `sim` para adicionar o diretório `bin` do framework ao PATH.
Enter ou `N` não altera o arquivo. Zsh usa `~/.zshrc`; Bash usa
`~/.bash_profile`. A entrada possui marcadores e não é duplicada em execuções
seguintes.

Carregue o profile alterado na sessão atual:

```bash
# Zsh
source ~/.zshrc

# Bash
source ~/.bash_profile
```

Confirme que o comando está acessível:

```bash
command -v agent-kit
agent-kit version
```

O ajuste do PATH só é oferecido por `init` e `init --force`. `sync`, `doctor`,
`diff` e `install` nunca alteram o profile do shell. Em execução sem terminal
interativo, a alteração é ignorada mesmo quando `--yes` é usado.

## 3. Projeto novo

### 3.1 Inicializar

Exemplo genérico com OpenCode como harness de controle:

```bash
cd /caminho/do/projeto
agent-kit init \
  --profile generic \
  --harness opencode \
  --harness codex
```

Exemplo Flutter com identidade explícita para o ai-memory:

```bash
agent-kit init \
  --profile flutter \
  --harness opencode \
  --harness codex \
  --memory-workspace flexidrive \
  --memory-project app-aluno
```

Exemplo instalando os quatro harnesses:

```bash
agent-kit init \
  --profile generic \
  --harness opencode \
  --harness codex \
  --harness copilot \
  --harness claude
```

O comando cria ou atualiza os assets gerenciados, adapters, catálogo de modelos
e `.ai-memory.toml`. Um `.ai-memory.toml` preexistente é sempre preservado.

### 3.2 Validar a instalação

```bash
agent-kit doctor
agent-kit diff
agent-kit catalog show
```

Resultado esperado:

```text
DOCTOR: PASS profile=generic framework=1.x.x
```

Se usar os prompts globais do Codex, registre também o framework no ambiente do
usuário:

```bash
agent-kit install
```

Depois reinicie a sessão do Codex para carregar os prompts globais.

### 3.3 Diagnosticar e reparar o ambiente local

Use este diagnóstico antes de atribuir um problema ao projeto. Ele verifica
Node.js, npm, npx, ai-memory, Caveman, TLC Spec-Driven e as integrações dos
harnesses encontradas no PATH:

```bash
agent-kit env --check
```

`--check` nunca instala, configura ou inicia serviços. A saída é `0` quando
todas as dependências obrigatórias estão prontas e `1` quando há pendência.
Para automação de inventário, use a mesma checagem em formato estruturado:

```bash
agent-kit env --check --json
```

`--json` também é somente leitura e não pode ser combinado com `--yes`.
Erros internos ou uso inválido de flags retornam `2`.

Quando houver uma ação conhecida e segura, rode o comando sem flag em um
terminal interativo. Ele mostra o plano antes de qualquer download, instalação
ou alteração de configuração:

```bash
agent-kit env
# revise PLANNED CHANGES
# responda y somente se quiser aplicar o plano
```

Para uma automação já revisada, use:

```bash
agent-kit env --yes
```

O comando só executa rotas oficiais fixas. Ele não instala Node.js, não usa
`curl | sh`, não avalia conteúdo baixado como shell e não aceita URLs
informadas pelo usuário. Reexecutar o mesmo plano é seguro: serviços são
recarregados sem duplicar o LaunchAgent, e instaladores de skills precisam
validar o resultado antes de serem reportados como concluídos.

No macOS, um ai-memory ausente pode ser instalado da release oficial para a
arquitetura `arm64`/`aarch64` ou `x86_64`, inicializado e registrado como
LaunchAgent. `ai-memory init` prepara os dados; o LaunchAgent é a etapa que
inicia o serviço. Em Linux e Windows, o comando diagnostica ai-memory, mas não
faz instalação automática.

As integrações de ai-memory seguem a capacidade de cada harness:

- Codex: MCP e hooks.
- OpenCode: MCP e plugin de ciclo de vida.
- Copilot: somente MCP em `.vscode/mcp.json`; hooks não são suportados.

Caveman é verificado pelo CLI oficial quando disponível e por diretórios
globais conhecidos. TLC Spec-Driven só é aceito como instalado quando a origem
oficial `tech-leads-club/agent-skills` também pode ser verificada; uma skill de
nome parecido ou copiada sem origem não é tratada como sucesso. Se Node.js,
npm ou npx estiver ausente, instale-os fora do `agent-kit` e execute
`agent-kit env --check` novamente.

### 3.4 Iniciar uma feature

No OpenCode:

```text
/feature cadastro de fazendas
```

No Codex:

```text
/prompts:feature cadastro de fazendas
```

Nos demais harnesses, invoque o prompt/comando `feature` instalado no projeto.
O fluxo cria a proposta de execução antes de despachar agentes.

## 4. Projeto existente: diagnóstico e `sync`

Use esta sequência quando o framework já está instalado e o projeto precisa
receber uma atualização normal:

```bash
cd /caminho/do/projeto
agent-kit status
agent-kit diff
agent-kit doctor
agent-kit sync
agent-kit doctor
agent-kit diff
```

`diff` não modifica arquivos. `sync` atualiza somente assets registrados como
pertencentes ao framework. Código, `.specs`, regras do projeto, extensões não
gerenciadas e `.ai-memory.toml` permanecem intactos.

Se um adapter gerenciado foi editado manualmente, `sync` para com uma mensagem
de proteção. Revise o arquivo e, somente quando quiser restaurar a versão do
framework, execute:

```bash
agent-kit sync --replace-managed
```

O conteúdo substituído recebe backup em `.agent-managed/backups/`.

## 5. Projeto existente: reinstalação com `init --force`

Use `--force` quando a instalação estiver incompleta, corrompida ou quando for
necessário trocar profile/harnesses.

### 5.1 Reinstalar usando o manifesto atual

```bash
agent-kit init --force
```

O comando mostra todos os paths afetados e pergunta:

```text
Reinstall framework-owned configuration? [y/N]:
```

Depois da reinstalação, caso o PATH ainda não esteja configurado, ele faz a
pergunta independente sobre `~/.zshrc` ou `~/.bash_profile`.

### 5.2 Trocar profile ou harnesses

```bash
agent-kit init --force \
  --profile flutter \
  --harness opencode \
  --harness claude
```

### 5.3 Reutilizar o catálogo validado

```bash
agent-kit init --force --reuse-model-lock
```

### 5.4 Automação sem TTY

```bash
agent-kit init --force --yes
```

`--yes` confirma a reinstalação do projeto, mas não autoriza alteração do shell
profile. O PATH só é alterado após resposta interativa específica.

Toda reinstalação cria um snapshot em
`.agent-managed/backups/reinstall-<id>/`. Se uma etapa falhar, o inventário
anterior é restaurado.

## 6. Ver tarefas em aberto

Liste tarefas cujo status ainda não é `passed`:

```bash
agent-kit tasks list
```

Exemplo de saída:

```text
OPEN_TASKS: 2
FEATURE TASK STATUS COMPLEXITY RISK TITLE
checkout T33* implementing MEDIUM MEDIUM Implementar pagamento
checkout T34 blocked HIGH HIGH Validar isolamento
```

O `*` identifica a tarefa atual da feature.

Filtre por feature:

```bash
agent-kit tasks list --feature checkout
```

Filtre por um ou mais status:

```bash
agent-kit tasks list --status blocked
agent-kit tasks list --status ready --status implementing
```

Inclua tarefas concluídas:

```bash
agent-kit tasks list --all
```

Consuma o resultado por script:

```bash
agent-kit tasks list --json
agent-kit tasks list --feature checkout --status blocked --json
```

A listagem lê o estado canônico em `.specs/features/*/state.json`, ou no
`state.path` project-owned configurado no manifesto. Estado inválido é
reportado em vez de ser ignorado silenciosamente.

## 7. Continuar uma tarefa

### 7.1 Fluxo recomendado dentro do OpenCode

```text
/continue T33 --provider=openai
```

O Orchestrator apresenta uma matriz para os papéis envolvidos:

```text
ROLE          RECOMMENDED             PROVIDER  EFFORT
orchestrator  modelo de controle      opencode  low
developer     modelo econômico apto   openai    low
reviewer      modelo de revisão       openai    medium
qa            modelo de QA            openai    low
```

Escolha uma ação:

```text
1=approve 2=change-models 3=show-justification 4=cancel
```

### 7.2 Deixar framework escolher provider e modelos

```bash
agent-kit continue T33 --harness opencode
```

Sem `--provider`, o valor é `auto`. O framework usa classificação, piso de
capacidade, catálogo e histórico de consumo para recomendar cada papel.

Para aprovar automaticamente as recomendações:

```bash
agent-kit continue T33 --harness opencode --yes
```

### 7.3 Fixar somente o provider

```bash
agent-kit continue T33 \
  --harness opencode \
  --provider openai
```

Providers explícitos são estritos. Nesse exemplo, Developer, Reviewer e QA não
podem migrar silenciosamente para outro provider. O Orchestrator continua no
modelo de controle persistido na instalação.

Exemplos usuais por harness:

```bash
agent-kit continue T33 --harness codex --provider openai
agent-kit continue T33 --harness copilot --provider copilot
agent-kit continue T33 --harness claude --provider claude
```

### 7.4 Selecionar modelos manualmente

Primeiro gere a proposta sem aprová-la:

```bash
agent-kit continue T33 \
  --harness opencode \
  --provider openai \
  --propose
```

Copie o identificador exibido em `MODEL_PROPOSAL` e aprove com os overrides:

```bash
agent-kit continue \
  --approve <proposal-id> \
  --model developer=<model-id> \
  --model reviewer=<model-id> \
  --model qa=<model-id>
```

É permitido escolher um modelo acima do piso. Um modelo abaixo do piso aparece
desabilitado e é recusado. Os overrides valem somente para essa atividade.

Para integração com scripts:

```bash
agent-kit continue T33 \
  --harness opencode \
  --provider openai \
  --propose \
  --json
```

Em ambiente sem TTY, use `--propose`, `--approve` ou `--yes`. Caso contrário, o
comando retorna `INTERACTION_REQUIRED`.

### 7.5 Entender a recomendação antes de executar

```bash
agent-kit route explain T33 \
  --workflow continue \
  --harness opencode \
  --provider openai

agent-kit route simulate T33 \
  --workflow continue \
  --harness opencode \
  --provider openai \
  --json
```

### 7.6 Alterar o modelo persistente do Orchestrator

O modelo do Orchestrator não muda por atividade. Atualize-o de forma explícita:

```bash
agent-kit catalog refresh --orchestrator-model <model-id>
```

Ou durante uma reinstalação:

```bash
agent-kit init --force \
  --orchestrator-model <model-id>
```

Se o modelo não estiver disponível ou não alcançar o piso do control plane, o
comando retorna `ORCHESTRATOR_UNAVAILABLE` sem downgrade silencioso.

## 8. Catálogo, consumo e fallback

Atualize e consulte os modelos conhecidos:

```bash
agent-kit catalog refresh
agent-kit catalog show
```

Veja o consumo registrado:

```bash
agent-kit usage report
agent-kit usage report --json
```

Após amostras suficientes, custo conhecido ou tokens históricos reordenam os
candidatos elegíveis. O histórico nunca reduz pisos, gates ou independência de
Reviewer/QA.

Quando um modelo aprovado falhar por quota ou indisponibilidade, o Orchestrator
usa apenas a próxima opção que já estava no plano aprovado. Operação manual para
diagnóstico:

```bash
agent-kit dispatch next-fallback \
  --plan <plan-id> \
  --role developer \
  --failed-model <model-id> \
  --json
```

Sem fallback aprovado, o resultado é `CIRCUIT_OPEN` e uma nova proposta deve ser
gerada.

## 9. Sequências completas

### Projeto novo com OpenCode e seleção interativa

```bash
cd /caminho/do/projeto
/caminho/para/framework/bin/agent-kit init \
  --profile generic \
  --harness opencode
# responda y quando quiser configurar o PATH
source ~/.zshrc
agent-kit doctor
```

Depois, no OpenCode:

```text
/feature minha feature
/continue T1 --provider=auto
```

### Projeto existente com atualização normal

```bash
cd /caminho/do/projeto
agent-kit diff
agent-kit sync
agent-kit doctor
agent-kit tasks list
```

### Projeto existente com instalação corrompida

```bash
cd /caminho/do/projeto
agent-kit init --force
# revise os paths e confirme a reinstalação
agent-kit doctor
agent-kit diff
```

### CI usando recomendações automáticas

```bash
agent-kit init --force --yes
agent-kit doctor
agent-kit continue T33 \
  --harness opencode \
  --provider openai \
  --yes \
  --json
```

O último comando cria um `DispatchPlan` aprovado. A execução efetiva continua no
harness. O CLI não finge que executou um agente quando apenas propôs ou aprovou
o plano.

## 10. Diagnóstico rápido

```bash
agent-kit status
agent-kit doctor
agent-kit env --check
agent-kit diff
agent-kit tasks list
agent-kit catalog show
agent-kit usage report
```

Se um projeto OpenCode antigo ainda encerrar o Orchestrator por limite de
etapas, execute `agent-kit sync`. Os adapters atuais não gravam `steps` no
Orchestrator.

## 11. Convergência: validar antes de revisar

O Developer continua sendo o único papel que altera código. Depois da alteração,
ele descobre os comandos do projeto e executa somente os gates necessários para
a tarefa: normalmente formatar os arquivos tocados, analisar/lintar e rodar os
testes focados. Reviewer não formata nem corrige código. QA só executa
verificação não mutante quando a tarefa, risco, aceitação ou regra do projeto o
exige.

Para uma tarefa formal com fronteira explícita, o Orchestrator registra os
fatos de gate e a closure. Exemplo Flutter conceitual:

```bash
FRAMEWORK_STATE=.agent-managed/agent-engineering-framework/state/state.py

python3 "$FRAMEWORK_STATE" gate-decision design-system T1 format \
  --command "dart format lib/text_field.dart" \
  --scope lib/text_field.dart

dart format lib/text_field.dart
python3 "$FRAMEWORK_STATE" gate design-system developer-format PASS \
  --task T1 --role developer --kind format \
  --scope lib/text_field.dart \
  --command "dart format lib/text_field.dart" \
  --evidence "formatted"

flutter analyze
python3 "$FRAMEWORK_STATE" gate design-system developer-analyze PASS \
  --task T1 --role developer --kind static-analysis \
  --scope lib/text_field.dart \
  --command "flutter analyze" --evidence "pass"

flutter test test/text_field_test.dart
python3 "$FRAMEWORK_STATE" gate design-system developer-tests PASS \
  --task T1 --role developer --kind focused-tests \
  --scope lib/text_field.dart \
  --command "flutter test test/text_field_test.dart" --evidence "pass"

python3 "$FRAMEWORK_STATE" developer-close design-system T1 \
  --require format,static-analysis,focused-tests \
  --scope lib/text_field.dart
```

O `gate-decision` retorna `REUSE_PASS` quando o mesmo gate já passou para a
mesma fonte e escopo. Depois de um FAIL idêntico, ele retorna bloqueio de falta
de progresso em vez de testar novamente sem mudança relevante. Altere a fonte,
rode os gates afetados e gere uma nova closure.

Depois, a revisão recebe uma única rodada e devolve um lote de findings:

```bash
python3 "$FRAMEWORK_STATE" review-start design-system T1
python3 "$FRAMEWORK_STATE" review-result design-system T1 CHANGES_REQUESTED \
  --findings '[
    {"severity":"MAJOR","file":"lib/text_field.dart:42","issue":"caso obrigatório sem validação"},
    {"severity":"MINOR","file":"lib/text_field.dart:17","issue":"mensagem pode ser mais clara"}
  ]'
```

`BLOCKER` e `MAJOR` retornam uma única correção ao Developer. `MINOR` fica
registrado, mas não abre outro ciclo automaticamente. Após o limite de rodadas
ou de falta de progresso, a tarefa fica `blocked` e a feature entra em
`human_escalation`; o operador decide o próximo passo. Falhas externas, como
quota, ferramenta indisponível ou `EXTERNAL_DIRTY_WORKTREE`, são registradas
separadamente e não consomem o budget de convergência.
