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
2. Expanda os cofres e pastas que deseja consultar.
3. Selecione os itens; use Ctrl para selecionar mais de um.
4. Escolha o destino e se deseja incluir subpastas.
5. Clique em **Baixar selecionados** ou **Baixar tudo da conta** e confirme o resumo.
6. Acompanhe o resultado e as mensagens de erro.

A árvore carrega subpastas sob demanda. O resumo mostra as pastas e os destinos locais. **Cancelar download** encerra a sessão; entre novamente para outra operação.

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
