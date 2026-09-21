"""Cria um commit das alterações locais e envia a branch atual ao origin.

Uso: python enviar_github.py -m "Atualiza documentação"
Prévia sem alterações: python enviar_github.py --dry-run
Usa a autenticação já configurada no Git, sem armazenar credenciais.
"""

import argparse
from pathlib import Path
import subprocess
import sys


def git(repo, *args, capture=False, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        stdout=subprocess.PIPE if capture else None,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def publish(repo, message, dry_run=False):
    root = Path(git(repo, "rev-parse", "--show-toplevel", capture=True).stdout.strip())
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer"):
        path = Path(git(root, "rev-parse", "--git-path", marker, capture=True).stdout.strip())
        if not path.is_absolute():
            path = root / path
        if path.exists():
            raise RuntimeError(
                "Há uma operação Git em andamento. Execute 'git status' e conclua "
                "ou aborte essa operação antes de executar este script. "
                "Para rebase, após resolver os conflitos: git add <arquivos> e git rebase --continue."
            )

    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", capture=True, check=False)
    if branch.returncode != 0:
        raise RuntimeError("HEAD está sem branch. Selecione a branch desejada com git switch antes de enviar.")
    branch = branch.stdout.strip()
    git(root, "remote", "get-url", "origin", capture=True)
    print(f"Repositório: {root}\nDestino: origin / {branch}", flush=True)
    git(root, "status", "--short")
    if dry_run:
        print(f"Prévia: git add -A; commit com mensagem {message!r}; push para origin/{branch}.")
        print("Nenhum arquivo, commit ou referência remota foi alterado.")
        return

    # Inclui novos arquivos, alterações e remoções, respeitando o .gitignore.
    git(root, "add", "-A")
    changes = git(root, "diff", "--cached", "--quiet", check=False)
    if changes.returncode == 1:
        git(root, "diff", "--cached", "--check")
        git(root, "commit", "-m", message)
    elif changes.returncode == 0:
        print("Sem alterações para commit; enviando eventuais commits locais pendentes.", flush=True)
    else:
        raise RuntimeError("Não foi possível verificar as alterações preparadas para commit.")
    # Sem force: divergências no remoto são rejeitadas pelo próprio Git.
    git(root, "push", "--set-upstream", "origin", f"HEAD:refs/heads/{branch}")
    print("Envio concluído.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-m", "--mensagem", default="Atualiza projeto e documentação", help="Mensagem do commit")
    parser.add_argument("--dry-run", action="store_true", help="Exibe a operação sem criar commit ou fazer push")
    args = parser.parse_args()
    if not args.mensagem.strip():
        parser.error("A mensagem do commit não pode estar vazia.")
    try:
        publish(Path(__file__).resolve().parent, args.mensagem, args.dry_run)
    except FileNotFoundError:
        print("Erro: Git não encontrado. Instale o Git e disponibilize-o no PATH.", file=sys.stderr)
        return 1
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Envio interrompido: {exc}", file=sys.stderr)
        print("Confira a mensagem do Git acima. Se o push falhou, o commit local permanece; "
              "corrija a autenticação ou divergência e execute novamente.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
