#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path, PurePosixPath

import yaml


MANIFEST_NAME = "release-manifest.yaml"
NOTES_NAME = "RELEASE-NOTES.md"
FRAMEWORK_ROOT_ENTRIES = {
    ".git",
    ".github",
    ".gitignore",
    ".gitattributes",
    "README.md",
    "schema",
    "scripts",
}
ALLOWED_ROOT_DIRECTORIES = {
    "artifacts",
    "compliance",
    "configuration",
    "docs",
    "evidence",
    "other",
    "sources",
}
CATEGORY_DIRECTORIES = {
    "sources": ("sources",),
    "artifacts": ("artifacts",),
    "configuration": ("configuration",),
    "docs/technical": ("docs", "technical"),
    "docs/user": ("docs", "user"),
    "evidence": ("evidence",),
    "compliance": ("compliance",),
    "other": ("other",),
}
FOLDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ARTIFACT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def as_mapping(value, field: str) -> dict:
    if not isinstance(value, dict):
        fail(f"{field} deve essere un oggetto")
    return value


def as_string(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{field} deve essere una stringa non vuota")
    return value


def validate_classification(entry: dict, prefix: str) -> None:
    if entry.get("category") == "other":
        as_string(entry.get("classificationReason"), f"{prefix}.classificationReason")


def validate_folder(value, index: int) -> dict:
    prefix = f"materials.folders[{index}]"
    folder = as_mapping(value, prefix)

    name = as_string(folder.get("name"), f"{prefix}.name")
    if not FOLDER_NAME_PATTERN.fullmatch(name):
        fail(f"{prefix}.name non rispetta lo slug richiesto")

    category = as_string(folder.get("category"), f"{prefix}.category")
    if category not in CATEGORY_DIRECTORIES:
        fail(f"Categoria non supportata: {category}")

    as_string(folder.get("description"), f"{prefix}.description")
    validate_classification(folder, prefix)

    return folder


def validate_artifact(value, index: int) -> dict:
    prefix = f"materials.artifacts[{index}]"
    artifact = as_mapping(value, prefix)

    name = as_string(artifact.get("name"), f"{prefix}.name")
    if not ARTIFACT_NAME_PATTERN.fullmatch(name):
        fail(
            f"{prefix}.name deve essere un nome file valido "
            "(nessuno slash, nessuno spazio)"
        )

    category = as_string(artifact.get("category"), f"{prefix}.category")
    if category not in CATEGORY_DIRECTORIES:
        fail(f"Categoria non supportata: {category}")

    as_string(artifact.get("description"), f"{prefix}.description")
    validate_classification(artifact, prefix)

    return artifact


def validate_manifest(repository: Path) -> tuple[list[dict], list[dict]]:
    manifest_path = repository / MANIFEST_NAME
    if not manifest_path.is_file():
        fail(f"Manca {MANIFEST_NAME} alla root")
    if not (repository / NOTES_NAME).is_file():
        fail(f"Manca {NOTES_NAME} alla root")

    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest = yaml.safe_load(stream)
    except yaml.YAMLError as error:
        fail(f"Manifest YAML non valido: {error}")

    manifest = as_mapping(manifest, "manifest")
    if manifest.get("schemaVersion") != 2:
        fail("schemaVersion deve essere 2")

    supplier = as_mapping(manifest.get("supplier"), "supplier")
    as_string(supplier.get("name"), "supplier.name")
    supplier_version = as_string(manifest.get("supplierVersion"), "supplierVersion")
    if len(supplier_version) > 128:
        fail("supplierVersion supera 128 caratteri")

    materials = as_mapping(manifest.get("materials"), "materials")
    folders_value = materials.get("folders", [])
    artifacts_value = materials.get("artifacts", [])
    if not isinstance(folders_value, list):
        fail("materials.folders deve essere una lista")
    if not isinstance(artifacts_value, list):
        fail("materials.artifacts deve essere una lista")

    folders = []
    folder_names = set()
    folder_categories = set()
    for index, value in enumerate(folders_value):
        folder = validate_folder(value, index)
        if folder["name"] in folder_names:
            fail(f"Nome cartella duplicato: {folder['name']}")
        folder_names.add(folder["name"])
        if folder["category"] in folder_categories:
            fail(f"Categoria dichiarata piu' volte tra le folders: {folder['category']}")
        folder_categories.add(folder["category"])
        folders.append(folder)

    artifacts = []
    artifact_names = set()
    for index, value in enumerate(artifacts_value):
        artifact = validate_artifact(value, index)
        if artifact["name"] in artifact_names:
            fail(f"Nome asset duplicato: {artifact['name']}")
        artifact_names.add(artifact["name"])
        artifacts.append(artifact)

    return folders, artifacts


def check_no_symlinks(path: Path) -> None:
    if path.is_symlink():
        fail(f"Symlink non consentito: {path}")
    for child in path.rglob("*"):
        if child.is_symlink():
            fail(f"Symlink non consentito: {child}")


def validate_tree(repository: Path, folders: list[dict]) -> None:
    allowed_root_files = {MANIFEST_NAME, NOTES_NAME}
    for entry in repository.iterdir():
        if entry.name in FRAMEWORK_ROOT_ENTRIES:
            continue
        if entry.is_file() and entry.name not in allowed_root_files:
            fail(f"File non consentito alla root: {entry.name}")
        if entry.is_dir() and entry.name not in ALLOWED_ROOT_DIRECTORIES:
            fail(f"Directory non consentita alla root: {entry.name}")

    covered_dirs: list[Path] = []
    for folder in folders:
        relative = PurePosixPath(*CATEGORY_DIRECTORIES[folder["category"]])
        local_path = repository.joinpath(*relative.parts)
        if not local_path.is_dir():
            fail(f"Cartella dichiarata non trovata: {relative}/")
        check_no_symlinks(local_path)
        if not any(child.is_file() for child in local_path.rglob("*")):
            fail(f"Cartella dichiarata ma vuota: {relative}/")
        covered_dirs.append(local_path)

    for root_name in ALLOWED_ROOT_DIRECTORIES:
        root = repository / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if not any(
                file_path == covered or covered in file_path.parents
                for covered in covered_dirs
            ):
                fail(
                    "File non inventariato (nessuna cartella dichiarata lo copre): "
                    f"{file_path.relative_to(repository)}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    repository = args.repo.resolve()

    try:
        folders, _artifacts = validate_manifest(repository)
        validate_tree(repository, folders)
    except ValidationError as error:
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        return 1

    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
