# D4Sign Central Bolsas

Aplicativo Python para baixar PDFs do D4Sign por automação do Chrome. A interface desktop permite entrar na conta, selecionar cofres e pastas e acompanhar os downloads. O modo terminal processa um cofre configurado.

## Executar em desenvolvimento

Use Windows e Python 3.12, a versão usada pelo workflow do projeto. No diretório deste README:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

`python main.py` abre a interface desktop. `python desktop.py` continua disponível como alternativa. Para executar a automação pelo terminal, use `python main.py --cli`.

O código atual exige estes arquivos no perfil do usuário:

```text
%USERPROFILE%\Chrome\chromedriver.exe
%USERPROFILE%\Chrome\GoogleChrome\App\Chrome-bin\chrome.exe
```

O ChromeDriver deve ser compatível com esse Chrome. Apenas instalar o Chrome no caminho padrão não atende à configuração atual de [browser.py](d4sign/browser.py). Embora seja uma dependência do projeto, `webdriver-manager` não é usado para baixar o driver na inicialização atual.

## Usar o desktop

1. Informe e-mail e senha e clique em **Entrar**.
2. Clique no nome de um cofre ou pasta para abrir. Use **Início** ou os níveis do caminho para voltar.
3. Marque as caixas das pastas que deseja baixar. A seleção permanece ao navegar.
4. Se precisar, use **Revisar** para consultar a seleção e **Destino e subpastas** para alterar onde salvar.
5. Clique em **Baixar pasta** ou **Baixar N pastas**. Não há confirmação adicional.
6. Acompanhe o resultado na própria tela. Em caso de falha, use **Tentar novamente**.

As subpastas são carregadas sob demanda. A busca ignora maiúsculas e minúsculas e pesquisa apenas no nível aberto. Listas grandes mostram 40 pastas por página; a caixa de seleção geral afeta somente essa página, respeitando a busca. **Atualizar** recarrega o nível atual e preserva as seleções ainda disponíveis.

Por padrão, o download inclui subpastas. Quando um pai está selecionado, seus descendentes aparecem incluídos e não precisam ser marcados novamente. **Cancelar download** encerra a sessão; entre novamente para outra operação.

A tela principal mostra apenas as ações de navegação e download. Configurações de destino e opções do aplicativo ficam recolhidas. Detalhes técnicos e atualização manual estão em **Opções do aplicativo**. O indicador de atividade é indeterminado: não representa uma porcentagem de documentos.

O explorador mostra pastas, não a lista de documentos. Uma pasta sem subpastas ainda pode conter PDFs.

O destino padrão é `~/Downloads/D4Sign`. A estrutura de cofres e pastas é mantida, e os PDFs recebem nomes como `Contrato - UUID.pdf`. Nomes incompatíveis com Windows são ajustados.

## Cache e arquivos

O desktop salva `.d4sign-cache.json` na pasta de destino. O terminal usa `cache.json` por padrão.

O JSON é excluído e recriado vazio quando a última gravação completa **2 dias (48 horas)**. A verificação ocorre na abertura do desktop para o destino padrão, no início do download para o destino escolhido e na inicialização do terminal. Cada gravação reinicia o prazo. Não existe limpeza com o aplicativo fechado.

A renovação do cache não apaga PDFs. O processamento verifica os arquivos existentes antes de decidir baixar novamente. Veja as [regras de PDFs repetidos](CORRECAO_PDFS_REPETIDOS.md).

## Diagnóstico e atualizações

O desktop usa `%LOCALAPPDATA%\D4SignDesktop` como diretório de trabalho para diagnósticos e arquivos temporários. As credenciais são usadas durante a sessão, sem gravação pelo aplicativo.

A interface consulta o repositório definido em [version.py](d4sign/version.py). Uma versão estável mais nova é baixada automaticamente; tamanho e SHA-256 são verificados antes de abrir o instalador. Falhas na consulta são informadas e permitem continuar usando a versão atual.

## Para desenvolvedores

- [Desenvolvimento](DESENVOLVIMENTO.md): arquitetura, configuração e manutenção.
- [Testes](test/README.md): instalação e comandos.
- [Cenários de teste](test/DOCUMENTACAO_TESTES.md): o que verificar ao mudar o código.
- [Gerar executável](<gerar novo executavel.md>): procedimento separado de empacotamento.

Os testes simulam o site. Login, mudanças no HTML do D4Sign e downloads precisam também de validação manual em uma conta de teste. Não há fluxo interativo implementado para CAPTCHA ou autenticação adicional.
