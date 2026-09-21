"""Integração com repositórios Git locais, sem acessar o GitHub."""
import shutil
import subprocess

import pytest

from enviar_github import publish


def run(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repositories(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git não disponível")
    remote, repo = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    run(repo, "config", "user.name", "Teste")
    run(repo, "config", "user.email", "teste@example.invalid")
    run(repo, "config", "commit.gpgsign", "false")
    run(repo, "remote", "add", "origin", str(remote))
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (repo / ".env").write_text("DADO_FICTICIO=teste\n", encoding="utf-8")
    (repo / "README.md").write_text("Documentação\n", encoding="utf-8")
    return repo, remote


def test_commit_push_and_retry_without_changes(repositories):
    repo, remote = repositories
    publish(repo, "Documentação")
    head = run(repo, "rev-parse", "HEAD")
    assert run(remote, "rev-parse", "refs/heads/main") == head
    assert ".env" not in run(repo, "ls-files").splitlines()
    publish(repo, "Sem alterações")
    assert run(repo, "rev-parse", "HEAD") == head


def test_dry_run_preserves_index_and_remote(repositories):
    repo, remote = repositories
    publish(repo, "Prévia", dry_run=True)
    assert run(repo, "ls-files") == ""
    assert run(remote, "for-each-ref") == ""


def test_rebase_blocks_before_staging(repositories):
    repo, remote = repositories
    (repo / ".git" / "rebase-merge").mkdir()
    with pytest.raises(RuntimeError, match="operação Git em andamento"):
        publish(repo, "Não publicar")
    assert run(repo, "ls-files") == ""
    assert run(remote, "for-each-ref") == ""
