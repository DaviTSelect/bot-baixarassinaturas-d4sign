# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

---

## [1.2.1] - 2026-11-12

### Corrigido
- `D4Sign.spec`: `python312.dll`, `vcruntime140.dll` excluídas do UPX — compressão corrompía a DLL causando crash "Failed to load Python DLL" ao tentar executar

---

## [1.1.8] - 2026-09-30

### Adicionado
- Explorador desktop D4Sign simplificado
- Versão final para produção

### Alterado
- Atualização do repositório

---

## [1.1.7] - 2026-09-01

### Adicionado
- Versão anterior estável

---

## [1.0.0] - 2026-01-01

### Adicionado
- Versão inicial: download de PDFs assinados do D4Sign
- Interface desktop PySide6
- Cache de sessão
- Build com PyInstaller + Inno Setup
- Atualização automática via GitHub Releases
