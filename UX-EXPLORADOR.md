# Análise do explorador D4Sign

## Arquitetura encontrada

A aplicação atual é desktop: `desktop.py` e `main.py` iniciam
`d4sign/desktop.py`, implementado com Tkinter/ttk. Não há servidor Flask,
endpoints HTTP, templates HTML, CSS ou módulos JavaScript de interface.
O JavaScript de `discovery.py` é executado pelo Selenium no site D4Sign.

1. **Pastas:** `Session.run()` autentica uma vez e chama
   `CatalogDiscovery.load()`, que lê o menu lateral da conta.
2. **Subpastas:** `Desktop.expand()` envia `expand` pela fila da sessão.
   `CatalogDiscovery.expand()` carrega apenas ramos ainda não carregados.
3. **Seleção:** o `ttk.Treeview` usa seleção múltipla com Ctrl. O estado vem
   de `tree.selection()`, misturando foco de navegação e escolha para download.
4. **Download:** `Desktop.start()` pede confirmação e envia IDs, opção
   recursiva e destino à sessão. `materialize()` descobre os descendentes;
   `selected_locations()` percorre cada localização uma vez, inclusive
   quando pai e filho aparecem na seleção. O processador mantém caminhos,
   cache, verificação dos PDFs e auditoria.
5. **Interface:** os widgets, estilos, eventos e mensagens estão concentrados
   em `d4sign/desktop.py`. Não existem arquivos web participantes.
6. **Feedback:** a sessão publica eventos de status e resultados por fila.
   Não fornece total global de documentos para percentual de progresso.

## Problemas de experiência

- Seleção dependente de Ctrl na árvore de navegação, sem checkboxes próprios.
- Ausência de breadcrumb, busca e resumo persistente da seleção.
- Ação de baixar toda a conta próxima das ações comuns.
- Confirmação modal para todo download.
- Erros técnicos exibidos em caixas de diálogo.
- Atualização recarrega o catálogo inteiro; uma falha encerra a sessão.
- Janela com tamanho mínimo de 700 × 650 e ações horizontais pouco flexíveis.
- O catálogo lista localizações, não documentos. Ausência de subpastas não
  comprova ausência de documentos: a interface não deve afirmar que uma
  pasta está completamente vazia com base somente nesse catálogo.

## Mudanças necessárias

Separar estado de navegação, filtro e seleção; usar checkboxes independentes
dos controles de abertura; preservar seleção entre níveis; eliminar seleção
redundante de descendentes quando a opção recursiva estiver ativa. Exibir
breadcrumb, busca claramente limitada ao nível atual, seleção dos resultados
visíveis, revisão da seleção e ação de download com quantidade.

Manter descoberta sob demanda e limitar a quantidade de linhas renderizadas.
Não buscar contagens de documentos apenas para decorar a tela. Usar progresso
indeterminado durante operações sem totais conhecidos e mensagens de erro
com recuperação, mantendo detalhes em logs.

Preservar autenticação, fila da sessão, download recursivo, caminhos locais,
cache e auditoria. Uma interface web exigiria uma camada nova de servidor e
segurança de sessão; isso não constitui apenas uma refatoração da tela atual.
A escolha entre desktop e web precisa ser definida antes da implementação.

## Validação prevista

Usar dados fictícios para verificar navegação e breadcrumb, seleção isolada,
múltiplas origens, pai/filho sem duplicidade, busca sem resultados, falhas e
repetição de operações, catálogo grande e preservação do download existente.
Validar teclado e dimensões reduzidas na plataforma escolhida. Testes com
conta real dependem de acesso autorizado e não devem gravar credenciais ou
documentos no repositório.
