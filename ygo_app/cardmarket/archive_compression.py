"""LZMA zip and Brotli helpers for Cardmarket R2 archives."""

from __future__ import annotations

import zipfile
from pathlib import Path

import brotli

LZMA_COMPRESSLEVEL = 9
BROTLI_QUALITY = 11
PRICES_EXPORT_MEMBER = "cardmarket_prices.json"


def write_lzma_zip(
    zip_path: Path,
    members: list[tuple[Path, str]],
) -> Path:
    """Write a ZIP archive using ZIP_LZMA at maximum compresslevel."""
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_LZMA,
        compresslevel=LZMA_COMPRESSLEVEL,
    ) as archive:
        for local_path, arcname in members:
            archive.write(local_path, arcname=arcname)
    return zip_path


def brotli_compress_bytes(data: bytes) -> bytes:
    return brotli.compress(data, quality=BROTLI_QUALITY)


def brotli_compress_file(src_path: Path) -> bytes:
    return brotli_compress_bytes(src_path.read_bytes())


def brotli_decompress_to_path(src_path: Path, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(brotli.decompress(src_path.read_bytes()))
    return dest_path


def extract_member_from_zip(
    zip_path: Path,
    member_name: str,
    dest_path: Path,
) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        dest_path.write_bytes(archive.read(member_name))
    return dest_path


def extract_prices_zip(zip_path: Path, dest_path: Path) -> Path:
    return extract_member_from_zip(zip_path, PRICES_EXPORT_MEMBER, dest_path)
