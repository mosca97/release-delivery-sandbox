#!/usr/bin/env python3

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path, PurePosixPath

import yaml


MANIFEST_NAME = "release-manifest.yaml"
NOTES_NAME = "RELEASE-NOTES.md"
FRAMEWORK_ROOT_ENTRIES = {".git", ".github", ".gitignore", "README.md", "schema", "scripts"}
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
MATERIAL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material_fingerprint(path: Path) -> tuple[int, str]:
    if path.is_symlink():
        fail(f"Symlink non consentito: {path}")

    if path.is_file():
        return path.stat().st_size, sha256_file(path)

    if not path.is_dir():
        fail(f"Materiale non trovato: {path}")

    entries = []
    total_size = 0
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            fail(f"Symlink non consentito: {child}")
        if not child.is_file():
            continue
        relative = child.relative_to(path).as_posix()
        entries.append(f"{relative}\t{sha256_file(child)}\n")
        total_size += child.stat().st_size

    canonical = "".join(entries).encode("utf-8")
    return total_size, hashlib.sha256(canonical).hexdigest()


def as_mapping(value, field: str) -> dict:
    if not isinstance(value, dict):
        fail(f"{field} deve essere un oggetto")
    return value


def as_string(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{field} deve essere una stringa non vuota")
    return value


def normalized_repository_path(value, field: str) -> PurePosixPath:
    path = as_string(value, field)
    if "\\" in path or path.startswith("/") or ".." in PurePosixPath(path).parts:
        fail(f"{field} deve essere un path POSIX relativo senza '..'")
    normalized = PurePosixPath(path.rstrip("/"))
    if str(normalized) in ("", "."):
        fail(f"{field} non puo essere vuoto")
    return normalized


def validate_manifest(repository: Path) -> list[dict]:
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
    if manifest.get("schemaVersion") != 1:
        fail("schemaVersion deve essere 1")

    supplier = as_mapping(manifest.get("supplier"), "supplier")
    as_string(supplier.get("name"), "supplier.name")
    supplier_version = as_string(manifest.get("supplierVersion"), "supplierVersion")
    if len(supplier_version) > 128:
        fail("supplierVersion supera 128 caratteri")

    materials = manifest.get("materials")
    if not isinstance(materials, list):
        fail("materials deve essere una lista")

    names = set()
    for index, material_value in enumerate(materials):
        prefix = f"materials[{index}]"
        material = as_mapping(material_value, prefix)
        name = as_string(material.get("name"), f"{prefix}.name")
        if not MATERIAL_NAME_PATTERN.fullmatch(name):
            fail(f"{prefix}.name non rispetta lo slug richiesto")
        if name in names:
            fail(f"Nome Material duplicato: {name}")
        names.add(name)

        category = as_string(material.get("category"), f"{prefix}.category")
        if category not in CATEGORY_DIRECTORIES:
            fail(f"Categoria non supportata: {category}")
        as_string(material.get("description"), f"{prefix}.description")
        if category == "other":
            as_string(
                material.get("classificationReason"),
                f"{prefix}.classificationReason",
            )

        size_bytes = material.get("sizeBytes")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            fail(f"{prefix}.sizeBytes deve essere un intero non negativo")
        sha256 = as_string(material.get("sha256"), f"{prefix}.sha256")
        if not SHA256_PATTERN.fullmatch(sha256):
            fail(f"{prefix}.sha256 deve essere uno SHA-256 esadecimale minuscolo")

        storage = as_mapping(material.get("storage"), f"{prefix}.storage")
        storage_type = as_string(storage.get("type"), f"{prefix}.storage.type")
        if storage_type in ("git", "git-lfs"):
            relative_path = normalized_repository_path(
                storage.get("path"), f"{prefix}.storage.path"
            )
            expected_prefix = PurePosixPath(*CATEGORY_DIRECTORIES[category])
            if not (
                relative_path == expected_prefix
                or expected_prefix in relative_path.parents
            ):
                fail(
                    f"{prefix}.storage.path deve ricadere sotto "
                    f"{expected_prefix}/"
                )

            local_path = repository.joinpath(*relative_path.parts)
            actual_size, actual_sha256 = material_fingerprint(local_path)
            if size_bytes != actual_size:
                fail(
                    f"{name}: sizeBytes dichiarato {size_bytes}, "
                    f"calcolato {actual_size}"
                )
            if sha256 != actual_sha256:
                fail(
                    f"{name}: sha256 dichiarato {sha256}, "
                    f"calcolato {actual_sha256}"
                )
        elif storage_type == "github-release":
            as_string(storage.get("asset"), f"{prefix}.storage.asset")
        elif storage_type == "github-packages":
            for field in ("packageType", "owner", "name", "version"):
                as_string(storage.get(field), f"{prefix}.storage.{field}")
        elif storage_type == "external":
            uri = as_string(storage.get("uri"), f"{prefix}.storage.uri")
            if "?" in uri or "#" in uri:
                fail(f"{prefix}.storage.uri non deve contenere query o fragment")
        else:
            fail(f"storage.type non supportato: {storage_type}")

    return materials


def validate_tree(repository: Path, materials: list[dict]) -> None:
    allowed_root_files = {MANIFEST_NAME, NOTES_NAME}
    for entry in repository.iterdir():
        if entry.name in FRAMEWORK_ROOT_ENTRIES:
            continue
        if entry.is_file() and entry.name not in allowed_root_files:
            fail(f"File non consentito alla root: {entry.name}")
        if entry.is_dir() and entry.name not in ALLOWED_ROOT_DIRECTORIES:
            fail(f"Directory non consentita alla root: {entry.name}")

    covered_files: dict[Path, str] = {}
    for material in materials:
        storage = material["storage"]
        if storage["type"] not in ("git", "git-lfs"):
            continue
        path = repository.joinpath(*PurePosixPath(storage["path"]).parts)
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = [child for child in path.rglob("*") if child.is_file()]
        else:
            fail(f"Materiale non trovato: {storage['path']}")
        for file_path in files:
            existing = covered_files.get(file_path)
            if existing:
                fail(
                    f"File coperto da piu Material: {file_path} "
                    f"({existing}, {material['name']})"
                )
            covered_files[file_path] = material["name"]

    for root_name in ALLOWED_ROOT_DIRECTORIES:
        root = repository / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if file_path.is_symlink():
                fail(f"Symlink non consentito: {file_path}")
            if file_path.is_file() and file_path not in covered_files:
                fail(f"File non inventariato: {file_path.relative_to(repository)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    repository = args.repo.resolve()

    try:
        materials = validate_manifest(repository)
        validate_tree(repository, materials)
    except ValidationError as error:
        print(f"VALIDATION FAILED: {error}", file=sys.stderr)
        return 1

    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
