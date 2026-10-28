"""Exact CSV-cell substitution. Standard library only; no network code.

Equality is exact Python string equality after strict CSV decoding/parsing.
Empty strings remain empty. No number parsing, trimming or Unicode normalization.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from typing import Callable

from . import __version__

SCHEMA = "sttm-sanitize.glossary.v1"
TOKEN = re.compile(r"v_[0-9a-f]{32}\Z")


class SanitizeError(Exception):
    """Safe, intentionally value-free user-facing error."""


@dataclass(frozen=True)
class Limits:
    max_files: int = 5
    max_fields: int = 10
    max_rows: int = 100
    max_file_bytes: int = 10 * 1024 * 1024
    max_field_chars: int = 131072

    def validate(self) -> None:
        if any(value < 1 for value in self.__dict__.values()):
            raise SanitizeError("All limits must be positive integers.")


@dataclass
class Dataset:
    dataset_id: str
    original_filename: str
    header: list[str]
    rows: list[list[str]]
    source_sha256: str

    @property
    def sanitized_filename(self) -> str:
        return self.dataset_id + ".csv"


@dataclass(frozen=True)
class Result:
    output: Path
    datasets: int
    rows: int
    cells: int
    unique_values: int
    scope_id: str


class Tokenizer:
    def __init__(self, token_factory: Callable[[], str] | None = None):
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self._new_token = token_factory or (lambda: "v_" + secrets.token_hex(16))

    def transform(self, value: str) -> str:
        if value == "":
            return ""
        if value in self.forward:
            return self.forward[value]
        for _ in range(100):
            token = self._new_token()
            if not TOKEN.fullmatch(token):
                raise SanitizeError("Token generator returned an invalid token.")
            if token not in self.reverse:
                self.forward[value] = token
                self.reverse[token] = value
                return token
        raise SanitizeError("Unable to allocate a unique token; no output published.")


def validate_delimiter(delimiter: str) -> None:
    if len(delimiter) != 1 or delimiter in '\r\n\0"':
        raise SanitizeError("Delimiter must be one character other than quote, NUL or newline.")


def read_dataset(path: Path, dataset_id: str, delimiter: str, encoding: str,
                 limits: Limits) -> Dataset:
    # A bounded single read also avoids hashing a different input snapshot.
    try:
        with path.open("rb") as stream:
            raw = stream.read(limits.max_file_bytes + 1)
    except OSError:
        raise SanitizeError(f"{dataset_id}: cannot read input file.") from None
    if len(raw) > limits.max_file_bytes:
        raise SanitizeError(f"{dataset_id}: input exceeds the file-size limit.")
    try:
        text = raw.decode(encoding, errors="strict")
    except (UnicodeError, LookupError):
        raise SanitizeError(f"{dataset_id}: cannot decode input; select the correct --encoding.") from None
    # TextIOWrapper-like newline handling without translating embedded CR/LF.
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(limits.max_field_chars)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter,
                            quotechar='"', strict=True, skipinitialspace=False)
        header = next(reader, None)
        if header is None or len(header) == 0:
            raise SanitizeError(f"{dataset_id}: CSV must start with a header record.")
        if len(header) > limits.max_fields:
            raise SanitizeError(f"{dataset_id}: field count exceeds --max-fields.")
        rows = []
        for record_index, row in enumerate(reader, start=1):
            if len(row) != len(header):
                raise SanitizeError(f"{dataset_id}: data record {record_index} has an incorrect field count; blank physical records are not skipped.")
            if len(rows) >= limits.max_rows:
                raise SanitizeError(f"{dataset_id}: row count exceeds --max-rows.")
            rows.append(row)
    except csv.Error:
        # Do not echo csv parser messages, input names, headers or cell content.
        raise SanitizeError(f"{dataset_id}: malformed CSV or field exceeds --max-field-chars.") from None
    finally:
        csv.field_size_limit(previous_limit)
    return Dataset(dataset_id, path.name, header, rows, hashlib.sha256(raw).hexdigest())


def write_private(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def encode_csv(header: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=",", quotechar='"',
                        quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def verify_archive(archive_path: Path, glossary: dict, datasets: list[Dataset]) -> None:
    """Verify serialized output, not just the tokenizer's in-memory maps."""
    try:
        if glossary["schema"] != SCHEMA:
            raise SanitizeError("Glossary schema verification failed.")
        reverse = glossary["values"]
        if any(not TOKEN.fullmatch(token) or not isinstance(value, str) or value == ""
               for token, value in reverse.items()):
            raise SanitizeError("Glossary value validation failed.")
        if len(set(reverse.values())) != len(reverse):
            raise SanitizeError("Glossary is not a one-to-one mapping.")
        expected = [dataset.sanitized_filename for dataset in datasets]
        if len(glossary["datasets"]) != len(datasets):
            raise SanitizeError("Glossary dataset count verification failed.")
        seen_tokens = set()
        with zipfile.ZipFile(archive_path) as archive:
            # Exact allowlist: neither glossary, README, original names nor paths.
            if archive.namelist() != expected or archive.testzip() is not None:
                raise SanitizeError("Upload archive content verification failed.")
            for dataset, metadata in zip(datasets, glossary["datasets"]):
                blob = archive.read(dataset.sanitized_filename)
                if metadata["sanitized_sha256"] != hashlib.sha256(blob).hexdigest():
                    raise SanitizeError("Sanitized CSV integrity verification failed.")
                if (metadata["dataset_id"] != dataset.dataset_id
                        or metadata["sanitized_filename"] != dataset.sanitized_filename
                        or metadata["original_filename"] != dataset.original_filename
                        or metadata["source_sha256"] != dataset.source_sha256
                        or metadata["row_count"] != len(dataset.rows)):
                    raise SanitizeError("Glossary metadata verification failed.")
                expected_fields = [{"field_id": f"f_{i:03d}", "original_name": name}
                                   for i, name in enumerate(dataset.header, start=1)]
                if metadata["fields"] != expected_fields:
                    raise SanitizeError("Header recovery verification failed.")
                records = list(csv.reader(io.StringIO(blob.decode("utf-8"), newline=""), strict=True))
                if not records or records[0] != [field["field_id"] for field in expected_fields]:
                    raise SanitizeError("Sanitized header verification failed.")
                if len(records) != len(dataset.rows) + 1:
                    raise SanitizeError("Sanitized row-count verification failed.")
                for sanitized, original in zip(records[1:], dataset.rows):
                    if len(sanitized) != len(original):
                        raise SanitizeError("Sanitized row-width verification failed.")
                    restored = []
                    for token in sanitized:
                        if token == "":
                            restored.append("")
                        else:
                            seen_tokens.add(token)
                            restored.append(reverse[token])
                    if restored != original:
                        raise SanitizeError("Cell-by-cell recovery verification failed.")
        if seen_tokens != set(reverse):
            raise SanitizeError("Glossary coverage verification failed.")
    except SanitizeError:
        raise
    except (KeyError, TypeError, ValueError, OSError, zipfile.BadZipFile, csv.Error):
        raise SanitizeError("Output verification failed; no output published.") from None


def sanitize(paths: list[Path], output: Path, *, delimiter: str = ",",
             encoding: str = "utf-8-sig", limits: Limits = Limits(),
             progress: Callable[[str], None] | None = None) -> Result:
    limits.validate()
    validate_delimiter(delimiter)
    if not 1 <= len(paths) <= limits.max_files:
        raise SanitizeError("Input file count exceeds --max-files or no CSV files were provided.")
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise SanitizeError("The same input file was selected more than once.")
    if any(path.suffix.lower() != ".csv" for path in paths):
        raise SanitizeError("Version 1 accepts CSV files only.")
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise SanitizeError("Output already exists; choose a new output directory. Nothing was overwritten.")
    if not output.parent.is_dir():
        raise SanitizeError("Output parent directory does not exist.")
    datasets = []
    for index, path in enumerate(paths, start=1):
        dataset_id = f"ds_{index:03d}"
        datasets.append(read_dataset(path, dataset_id, delimiter, encoding, limits))
        if progress:
            progress(f"Read {dataset_id}.")
    tokenizer = Tokenizer()
    scope_id = "scope_" + uuid.uuid4().hex
    glossary = {
        "schema": SCHEMA,
        "tool_version": __version__,
        "scope_id": scope_id,
        "equality": "exact_decoded_csv_string; empty_string_preserved",
        "source_format": {"delimiter": delimiter, "encoding": encoding, "header": True},
        "output_format": {"delimiter": ",", "encoding": "utf-8", "header": True},
        "datasets": [],
        "values": tokenizer.reverse,
        "verification": {"status": "pending"},
    }
    # Private temporary staging; no usable upload is published until readback passes.
    with tempfile.TemporaryDirectory(prefix=".sttm-sanitize-", dir=output.parent) as temp:
        stage = Path(temp)
        archive_path = stage / "UPLOAD_reports.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for dataset in datasets:
                fields = [{"field_id": f"f_{i:03d}", "original_name": name}
                          for i, name in enumerate(dataset.header, start=1)]
                rows = [[tokenizer.transform(value) for value in row] for row in dataset.rows]
                blob = encode_csv([field["field_id"] for field in fields], rows)
                archive.writestr(dataset.sanitized_filename, blob)
                glossary["datasets"].append({
                    "dataset_id": dataset.dataset_id,
                    "original_filename": dataset.original_filename,
                    "sanitized_filename": dataset.sanitized_filename,
                    "source_sha256": dataset.source_sha256,
                    "sanitized_sha256": hashlib.sha256(blob).hexdigest(),
                    "row_count": len(dataset.rows),
                    "fields": fields,
                })
        # Roundtrip the JSON before verifying, to catch serialization mistakes.
        serialized = json.dumps(glossary, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
        loaded = json.loads(serialized)
        verify_archive(archive_path, loaded, datasets)
        glossary["verification"] = {
            "status": "passed",
            "checks": ["upload_allowlist", "csv_readback", "bijective_value_mapping",
                       "exact_cell_recovery", "header_recovery", "row_order_and_duplicates",
                       "empty_strings", "mapping_coverage", "sha256"],
            "ese_sttm_parity": "NOT_RUN",
        }
        write_private(stage / "glossary.json", json.dumps(glossary, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        instructions = (
            "STTM SANITIZE - INSTRUCTIONS\n\n"
            "1. UPLOAD ONLY: UPLOAD_reports.zip (sanitized CSV files only).\n"
            "2. KEEP LOCAL: glossary.json. It contains original values and names in plaintext.\n"
            "3. Do not upload the entire output folder, glossary or source ZIP.\n"
            "4. Keep the glossary securely for as long as you need to recover original values.\n"
            "5. The CLI verifies recovery but does not provide a recovery command.\n"
            "6. There is no server or remote backup to recover a lost glossary.\n\n"
            "This is reversible tokenization, not encryption or full anonymization.\n"
            "Equality, frequencies, row order and table shape remain visible.\n"
            "Use only output from a run that prints PASS and exits with code 0.\n"
            f"Scope: {scope_id}\n"
        )
        write_private(stage / "HUONG_DAN.txt", instructions.encode("utf-8"))
        # Reserve a NEW directory without overwriting an existing directory/symlink.
        # Publish recovery first, upload last, so an upload never precedes its glossary.
        try:
            output.mkdir(mode=0o700)
        except FileExistsError:
            raise SanitizeError("Output appeared during processing; nothing was overwritten.") from None
        for name in ("glossary.json", "HUONG_DAN.txt", "UPLOAD_reports.zip"):
            write_private(output / name, (stage / name).read_bytes())
    return Result(output, len(datasets), sum(len(d.rows) for d in datasets),
                  sum(len(row) for d in datasets for row in d.rows),
                  len(tokenizer.reverse), scope_id)
