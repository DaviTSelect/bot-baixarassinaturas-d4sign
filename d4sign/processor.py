from __future__ import annotations

import hashlib
import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .models import Statistics
from .parser import DocumentParser
from .utils import sanitize_filename, is_pdf


class Processor:

    def __init__(
        self,
        config,
        browser,
        downloader,
        cache,
        progress=None,
    ):
        self.config = config
        self.browser = browser
        self.downloader = downloader
        self.cache = cache
        self.progress = progress

        # Índice usado para detectar PDFs duplicados por conteúdo sem
        # recalcular hash de todos os arquivos a cada documento.
        self._pdf_size_index: dict[Path, dict[int, set[Path]]] = {}
        self._pdf_hash_cache: dict[Path, tuple[int, int, str]] = {}
        self.last_audit: dict[str, object] = {}

    # =========================================================
    # CONTROLE DE DUPLICIDADE DE PDF
    # =========================================================

    @staticmethod
    def _mtime_ns(stat_result) -> int:
        """Retorna mtime em nanos, com fallback para objetos de teste/filesystems antigos."""
        value = getattr(stat_result, "st_mtime_ns", None)
        if value is not None:
            return int(value)
        return int(float(getattr(stat_result, "st_mtime", 0)) * 1_000_000_000)

    def _ensure_pdf_index(self, folder: Path) -> dict[int, set[Path]]:
        """Indexa PDFs existentes por tamanho. O SHA-256 é calculado somente quando necessário."""
        folder = Path(folder).resolve()

        if folder in self._pdf_size_index:
            return self._pdf_size_index[folder]

        index: dict[int, set[Path]] = {}

        if folder.exists():
            for pdf in folder.glob("*.pdf"):
                try:
                    if not pdf.is_file() or not is_pdf(pdf):
                        continue
                    resolved = pdf.resolve()
                    size = resolved.stat().st_size
                    index.setdefault(size, set()).add(resolved)
                except OSError:
                    continue

        self._pdf_size_index[folder] = index
        return index

    def _pdf_sha256(self, path: Path) -> str | None:
        """Calcula SHA-256 com cache invalidado automaticamente se tamanho/mtime mudar."""
        try:
            path = Path(path).resolve()
            stat_result = path.stat()
            signature = (
                int(stat_result.st_size),
                self._mtime_ns(stat_result),
            )

            cached = self._pdf_hash_cache.get(path)
            if cached and cached[:2] == signature:
                return cached[2]

            digest = hashlib.sha256()
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(chunk)

            value = digest.hexdigest()
            self._pdf_hash_cache[path] = (signature[0], signature[1], value)
            return value

        except (OSError, TypeError, ValueError):
            return None

    def _remove_from_pdf_index(self, path: Path) -> None:
        """Remove um caminho dos índices locais antes de apagar/substituir o arquivo."""
        try:
            resolved = Path(path).resolve()
        except (OSError, TypeError, ValueError):
            return

        self._pdf_hash_cache.pop(resolved, None)

        for index in self._pdf_size_index.values():
            for paths in index.values():
                paths.discard(resolved)

    def _add_to_pdf_index(self, path: Path) -> None:
        """Registra um PDF novo no índice da pasta, se o índice já tiver sido criado."""
        try:
            path = Path(path).resolve()
            folder = path.parent.resolve()
            if folder not in self._pdf_size_index:
                return
            size = path.stat().st_size
            self._pdf_size_index[folder].setdefault(size, set()).add(path)
            self._pdf_hash_cache.pop(path, None)
        except (OSError, TypeError, ValueError):
            return

    def _find_duplicate_pdf(
        self,
        candidate: Path,
        destination: Path,
    ) -> Path | None:
        """
        Retorna outro PDF da pasta com conteúdo idêntico ao candidato.

        O nome do arquivo não é usado para decidir duplicidade; a comparação
        final é feita por SHA-256. Primeiro filtramos pelo tamanho para manter
        a verificação rápida mesmo com milhares de PDFs.
        """
        try:
            candidate = Path(candidate).resolve()
            destination = Path(destination)
            folder = destination.parent.resolve()

            if not candidate.exists() or not candidate.is_file() or not is_pdf(candidate):
                return None

            size = candidate.stat().st_size
            index = self._ensure_pdf_index(folder)
            peers = list(index.get(size, set()))

            if not peers:
                return None

            candidate_hash = self._pdf_sha256(candidate)
            if not candidate_hash:
                return None

            for other in peers:
                try:
                    other = Path(other).resolve()
                    if other == candidate:
                        continue
                    if not other.exists() or not is_pdf(other):
                        continue
                    if self._pdf_sha256(other) == candidate_hash:
                        return other
                except (OSError, TypeError, ValueError):
                    continue

        except (OSError, TypeError, ValueError):
            return None

        return None

    def _invalidate_cached_document(self, project_id: str, uuid: str) -> None:
        """Marca cache inconsistente como não baixado quando a implementação suporta isso."""
        marker = getattr(self.cache, "mark_not_downloaded", None)
        if callable(marker):
            marker(project_id, uuid)

    def _audit_expected_files(
        self,
        expected_files: dict[str, Path],
    ) -> dict[str, object]:
        """Audita se todos os UUIDs esperados terminaram com PDFs válidos e únicos."""
        missing: list[str] = []
        duplicate_uuids: set[str] = set()
        duplicate_pairs: set[tuple[str, str]] = set()
        path_to_uuid = {
            Path(path).resolve(): uuid
            for uuid, path in expected_files.items()
        }

        for uuid, path in expected_files.items():
            path = Path(path)

            if not is_pdf(path):
                missing.append(uuid)
                continue

            duplicate = self._find_duplicate_pdf(path, path)
            if duplicate is None:
                continue

            duplicate = Path(duplicate).resolve()
            other_uuid = path_to_uuid.get(duplicate)

            duplicate_uuids.add(uuid)
            if other_uuid:
                duplicate_uuids.add(other_uuid)
                duplicate_pairs.add(tuple(sorted((uuid, other_uuid))))
            else:
                duplicate_pairs.add((uuid, duplicate.name))

        result = {
            "expected": len(expected_files),
            "valid_unique": len(expected_files) - len(set(missing)) - len(duplicate_uuids),
            "missing": sorted(set(missing)),
            "duplicate_uuids": sorted(duplicate_uuids),
            "duplicate_pairs": sorted(duplicate_pairs),
            "complete": not missing and not duplicate_uuids,
        }
        self.last_audit = result
        return result

    # =========================================================
    # PROCESSAR APENAS O LINK ESPECÍFICO
    # =========================================================

    def process_specific_link(self) -> Statistics:
        return self.process_location(self.config.vault_uuid, "Cofre_Especifico",
                                     self.config.download_dir / "Cofre_Especifico")

    def process_location(self, project_id: str, project_name: str, folder_dir: Path) -> Statistics:
        """
        Processa os documentos diretamente nesta localização, mantendo a
        paginação e a auditoria. A sessão percorre as subpastas separadamente.
        """
        stats = Statistics()

        print()
        print("=" * 70)
        print("PROCESSANDO APENAS O COFRE ESPECÍFICO")
        print("=" * 70)
        print(f"Projeto: {project_name}")
        print(f"ID (Link): {project_id}")

        cached_count = len(
            self.cache.get_project(project_id)
        )

        print(
            f"UUIDs no cache: {cached_count}"
        )

        # =====================================================
        # DIRETÓRIO DO PROJETO (Onde os PDFs serão salvos)
        # =====================================================

        folder_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # =====================================================
        # PAGINAÇÃO DO COFRE ESPECÍFICO
        # =====================================================

        page = 0
        expected_files: dict[str, Path] = {}
        seen_pages = set()

        while True:
            print()
            print("=" * 70)
            print(f"ABRINDO PÁGINA {page}")
            print("=" * 70)

            try:
                # Chama a navegação do Selenium passando apenas o UUID alvo
                rows = self.browser.open_folder_page(
                    project_id,
                    page,
                )

            except Exception as exc:
                print()
                print("✗ ERRO AO ABRIR PÁGINA")
                print(repr(exc))
                stats.errors += 1
                break

            # =================================================
            # NÃO HÁ MAIS DOCUMENTOS
            # =================================================

            if not rows:
                print()
                print(
                    f"Nenhum documento encontrado "
                    f"na página {page}."
                )
                break

            try:
                signature = tuple(DocumentParser.uuid(row) for row in rows)
            except Exception:
                signature = ()
            if any(signature):
                if signature in seen_pages:
                    raise RuntimeError(f"O site repetiu uma página de {project_name}. A listagem não pôde ser concluída.")
                seen_pages.add(signature)

            stats.pages += 1
            stats.documents += len(rows)

            print(
                f"Documentos encontrados na página: {len(rows)}"
            )

            # =================================================
            # DOCUMENTOS DA PÁGINA
            # =================================================

            for index, row in enumerate(
                rows,
                start=1,
            ):
                print()
                print("-" * 70)
                print(
                    f"DOCUMENTO {index}/{len(rows)}"
                )
                print("-" * 70)

                preview_uuid = None
                preview_name = "documento"
                try:
                    preview_uuid = DocumentParser.uuid(row)
                    preview_name = DocumentParser.name(row) or "documento"
                except Exception:
                    pass

                result = self.process_document(
                    row=row,
                    folder_dir=folder_dir,
                    project_id=project_id,
                )

                if preview_uuid and result != "skipped":
                    preview_uuid = str(preview_uuid).strip()
                    preview_name = str(preview_name).strip() or "documento"
                    expected_files[preview_uuid] = (
                        folder_dir
                        / f"{sanitize_filename(preview_name)} - {preview_uuid}.pdf"
                    )

                if result == "downloaded":
                    stats.downloaded += 1
                elif result == "cached":
                    stats.cached += 1
                elif result == "skipped":
                    stats.skipped += 1
                else:
                    stats.errors += 1

                if self.progress is not None:
                    self.progress(stats)

            # =================================================
            # PRÓXIMA PÁGINA
            # =================================================

            print()
            print("=" * 70)
            print(
                f"PÁGINA {page} CONCLUÍDA"
            )
            print("=" * 70)

            page += 1

        print()
        print("=" * 70)
        print("AUDITORIA FINAL DOS PDFs")
        print("=" * 70)

        audit = self._audit_expected_files(expected_files)

        if audit["complete"]:
            print(
                f"✓ Todos os {audit['expected']} documentos esperados "
                "possuem PDF válido e sem repetição por conteúdo."
            )
        else:
            print("✗ A auditoria final encontrou pendências.")
            print(f"  Esperados: {audit['expected']}")
            print(f"  Válidos e únicos: {audit['valid_unique']}")
            if audit["missing"]:
                print(f"  UUIDs sem PDF válido: {', '.join(audit['missing'])}")
            if audit["duplicate_uuids"]:
                print(
                    "  UUIDs com conteúdo repetido: "
                    + ", ".join(audit["duplicate_uuids"])
                )

        return stats

    # =========================================================
    # PROCESSAR DOCUMENTO
    # =========================================================

    def process_document(
        self,
        row,
        folder_dir: Path,
        project_id: str,
    ) -> str:

        uuid = DocumentParser.uuid(row)

        if not uuid:
            print("✗ UUID não encontrado.")
            return "error"

        uuid = str(uuid).strip()

        name = DocumentParser.name(row)
        if not name:
            name = "documento"

        name = str(name).strip()

        filename = f"{sanitize_filename(name)} - {uuid}.pdf"
        destination = folder_dir / filename

        print(f"Nome: {name}")
        print(f"UUID: {uuid}")
        print(f"\nDestino:\n{destination}")

        # -----------------------------------------------------
        # O DISCO É A FONTE DE VERDADE
        # -----------------------------------------------------
        # Um cache antigo pode afirmar que o UUID já foi baixado mesmo
        # quando o arquivo foi apagado/corrompido ou quando, por causa do
        # bug do seletor global, ele contém o MESMO PDF de outro UUID.
        existing_pdf = is_pdf(destination)

        if existing_pdf:
            duplicate = self._find_duplicate_pdf(
                destination,
                destination,
            )

            if duplicate is not None:
                print()
                print("⚠️ PDF REPETIDO DETECTADO NO DISCO.")
                print(f"   Atual: {destination.name}")
                print(f"   Igual a: {duplicate.name}")
                print("→ O arquivo repetido será descartado e baixado novamente.")

                self._remove_from_pdf_index(destination)
                try:
                    destination.unlink(missing_ok=True)
                except OSError as exc:
                    print(f"⚠️ Não foi possível remover o PDF repetido: {exc}")

                self._invalidate_cached_document(project_id, uuid)
                existing_pdf = False

        print("\nConsultando cache...")
        if self.cache.contains(project_id, uuid):
            if existing_pdf:
                print("✓ UUID encontrado no cache.")
                print("✓ PDF correspondente existe e é válido.")
                print("→ Pulando para o próximo.")
                return "cached"

            print("⚠️ UUID estava no cache, mas o PDF não existe/é inválido/repetido.")
            print("→ Cache será invalidado e o documento será baixado novamente.")
            self._invalidate_cached_document(project_id, uuid)
        else:
            print("→ UUID não encontrado no cache.")

        print("→ Documento será analisado.")

        if not DocumentParser.finalized(row):
            print("\n→ Documento não está FINALIZADO.")
            print("→ Não será baixado.")
            return "skipped"

        print("\n✓ Documento está FINALIZADO.")

        if existing_pdf:
            print("\n✓ PDF já existe no disco.")
            print("→ Adicionando UUID ao cache.")
            self.cache.add(project_id, uuid)
            return "cached"

        print("\n" + "=" * 70)
        print("INICIANDO DOWNLOAD")
        print("=" * 70)

        success = self.download_selenium(
            row=row,
            destination=destination,
        )

        if success:
            print("\n✓ DOWNLOAD CONFIRMADO.")
            if is_pdf(destination):
                self.cache.add(project_id, uuid)
                print("\n✓ UUID adicionado ao cache.")
                return "downloaded"

            print("\n✗ Download retornou sucesso, mas o PDF não foi encontrado.")
            return "error"

        print("\n✗ DOWNLOAD FALHOU.")
        print("✗ UUID NÃO será colocado no cache.")
        return "error"

    # =========================================================
    # DOWNLOAD SELENIUM COM DELAY E CARREGAMENTO COMPLETO
    # =========================================================

    def download_selenium(
        self,
        row,
        destination: Path,
    ) -> bool:

        driver = self.browser.driver
        download_dir = Path(self.config.download_dir)
        
        max_retries = max(
            1,
            int(getattr(self.config, "download_retries", 3)),
        )

        for attempt in range(1, max_retries + 1):
            print(f"\n>>> Tentativa de download {attempt}/{max_retries}...")

            try:
                arquivos_antes = {
                    arquivo.resolve()
                    for arquivo in download_dir.glob("*")
                    if arquivo.is_file()
                }

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(1)

                try:
                    menu_button = row.find_element(
                        By.CSS_SELECTOR,
                        "div.btn-group > i.dropdown-toggle, .dropdown-toggle, .fa-ellipsis-v, .fa-ellipsis-h"
                    )
                    driver.execute_script("arguments[0].click();", menu_button)
                    
                    print("✓ Menu de opções acionado. Aguardando carregamento dos elementos...")
                    time.sleep(2.0) 
                    
                except Exception as menu_exc:
                    print(f"⚠️ Aviso ao abrir menu (tentativa {attempt}): {menu_exc}")

                # IMPORTANTE: o link deve ser procurado DENTRO DA LINHA
                # atual. O XPath global usado anteriormente podia retornar o
                # primeiro link de download da página, fazendo vários UUIDs
                # baixarem exatamente o mesmo PDF.
                download_link = WebDriverWait(driver, 15).until(
                    lambda _driver: (
                        DocumentParser.download_element(row)
                        or False
                    )
                )

                href_attr = download_link.get_attribute("href")

                if not href_attr or "javascript:" not in href_attr:
                    onclick_attr = download_link.get_attribute("onclick")
                    if onclick_attr:
                        href_attr = f"javascript: {onclick_attr}"

                print("✓ Link 'Download (apenas assinaturas)' capturado com sucesso.")

                if href_attr and href_attr.startswith("javascript:"):
                    js_code = href_attr.replace("javascript:", "").strip()
                    driver.execute_script(js_code)
                else:
                    driver.execute_script("arguments[0].click();", download_link)

                print("✓ Comando disparado. Aguardando arquivo PDF...")

                timeout = getattr(
                    self.config,
                    "download_timeout",
                    120,
                )

                inicio = time.time()
                arquivo_pdf = None
                ultimo_aviso = 0

                while time.time() - inicio < timeout:
                    tempo_decorrido = int(time.time() - inicio)
                    
                    if tempo_decorrido - ultimo_aviso >= 5:
                        print(f"...aguardando arquivo há {tempo_decorrido}s...")
                        ultimo_aviso = tempo_decorrido

                    arquivos = [
                        arquivo
                        for arquivo in download_dir.glob("*")
                        if arquivo.is_file()
                    ]

                    novos = [
                        arquivo
                        for arquivo in arquivos
                        if arquivo.resolve() not in arquivos_antes
                    ]

                    temporarios = [
                        arquivo
                        for arquivo in novos
                        if (
                            arquivo.name.endswith(".crdownload")
                            or arquivo.name.endswith(".tmp")
                            or arquivo.name.endswith(".part")
                        )
                    ]

                    if temporarios:
                        time.sleep(1)
                        continue

                    pdfs = [
                        arquivo
                        for arquivo in novos
                        if arquivo.suffix.lower() == ".pdf"
                    ]

                    if pdfs:
                        arquivo_pdf = max(
                            pdfs,
                            key=lambda arquivo: arquivo.stat().st_mtime,
                        )

                        tamanho_1 = arquivo_pdf.stat().st_size
                        time.sleep(1.5)

                        if not arquivo_pdf.exists():
                            continue

                        tamanho_2 = arquivo_pdf.stat().st_size

                        if tamanho_1 > 0 and tamanho_1 == tamanho_2:
                            break

                    time.sleep(1)

                if arquivo_pdf:
                    if not is_pdf(arquivo_pdf):
                        print(
                            "⚠️ O arquivo recebido não é um PDF válido. "
                            "Tentando novamente."
                        )
                        try:
                            arquivo_pdf.unlink(missing_ok=True)
                        except OSError:
                            pass
                        arquivo_pdf = None
                        continue

                    duplicate = self._find_duplicate_pdf(
                        arquivo_pdf,
                        destination,
                    )

                    if duplicate is not None:
                        print()
                        print("⚠️ DOWNLOAD REPETIDO DETECTADO.")
                        print(f"   Recebido: {arquivo_pdf.name}")
                        print(f"   Já existe como: {duplicate.name}")
                        print("→ Este download NÃO será aceito para outro UUID.")
                        print("→ Tentando novamente o documento correto...")

                        try:
                            arquivo_pdf.unlink(missing_ok=True)
                        except OSError:
                            pass

                        arquivo_pdf = None
                        continue

                    destination.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    if destination.exists():
                        self._remove_from_pdf_index(destination)
                        try:
                            destination.unlink()
                        except OSError:
                            pass

                    arquivo_pdf.replace(destination)

                    if is_pdf(destination):
                        duplicate_after_move = self._find_duplicate_pdf(
                            destination,
                            destination,
                        )

                        if duplicate_after_move is not None:
                            print()
                            print("⚠️ PDF final ficou idêntico a outro documento.")
                            print(f"   Igual a: {duplicate_after_move.name}")
                            print("→ Removendo e tentando novamente.")
                            self._remove_from_pdf_index(destination)
                            try:
                                destination.unlink(missing_ok=True)
                            except OSError:
                                pass
                            continue

                        self._add_to_pdf_index(destination)
                        print("✓ DOWNLOAD CONCLUÍDO COM SUCESSO!")
                        return True

                print(f"⚠️ Tentativa {attempt} falhou: O arquivo PDF não apareceu a tempo.")

            except Exception as exc:
                print(f"⚠️ Erro na tentativa {attempt}: {repr(exc)}")

            time.sleep(3)

        print("\n✗ TIMEOUT / TODAS AS TENTATIVAS FALHARAM.")
        return False
