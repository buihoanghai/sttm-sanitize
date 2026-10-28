# sttm-sanitize — CSV CLI v0.1.0

A local CLI for reversible CSV tokenization. It replaces cell values with random
tokens and creates a private glossary for recovery.
**Upload only `UPLOAD_reports.zip`. Keep `glossary.json` on your own machine.**

Requires **Python 3.10+** and uses only the Python standard library. No package
installation, virtual environment, database, server, account or Internet is
required to run the tool.

## 1. Download and try it

Open https://github.com/buihoanghai/sttm-sanitize and select
**Code → Download ZIP**. Extract the ZIP and open a terminal in the extracted
folder, usually `sttm-sanitize-main`, containing `run.py` and `sttm_sanitize`.

Linux / macOS:

```bash
python3 --version
python3 -m sttm_sanitize --input examples --output demo-output
```

Windows PowerShell / CMD:

```powershell
py -3 --version
py -3 -m sttm_sanitize --input examples --output demo-output
```

If Windows has Python 3.10+ but no `py` command, use `python` instead of `py -3`.
Install Python from https://www.python.org/downloads/ if needed. There are no
packages to install. Windows/macOS execution has not been verified, and native
executables have not been built. No OS security bypass is required.

Output:

```text
demo-output/
  UPLOAD_reports.zip    ← upload ONLY this file
  glossary.json         ← keep LOCAL; contains originals in plaintext
  HUONG_DAN.txt          ← generated handling instructions
```

The output directory must not already exist, and its parent directory must
exist. To run again, choose a new name such as `--output demo-output-2`.
Existing input/output files are not overwritten. Output filenames remain part of the existing contract.

## 2. Sanitize all related reports together

Put all related CSV reports in one folder and process them in one invocation:

```bash
python3 -m sttm_sanitize --input reports --output new-output
```

Or select multiple files:

```bash
python3 -m sttm_sanitize --input sales.csv customers.csv --output new-output
```

Windows:

```powershell
py -3 -m sttm_sanitize --input "C:\Reports\sales.csv" "C:\Reports\customers.csv" --output "C:\Reports\sanitized-01"
```

All files in one run share a mapping. To preserve equality across reports,
process them in **the same run**. Do not combine outputs from separate runs or
manually merge/edit glossaries.

Folder selection reads CSV files directly inside that folder, without recursion.
Other file types in a selected folder are ignored. Explicitly selecting a file
without a `.csv` extension fails. Only CSV input is supported; Excel/XLSX, JSON
and ZIP files cannot be read directly. Quoted glob patterns are supported:

```bash
python3 -m sttm_sanitize --input "reports/*.csv" --output new-output
```

Input defaults to UTF-8 with or without a BOM and a comma delimiter. The first
record must be a header. Encoding and delimiter are never guessed:

```bash
python3 -m sttm_sanitize --input reports --output new-output --delimiter ";"
python3 -m sttm_sanitize --input reports --output new-output --delimiter tab
python3 -m sttm_sanitize --input reports --output new-output --encoding cp1252
```

One delimiter/encoding configuration applies to every input in a run. Output
is always UTF-8 comma CSV with CRLF and Python `csv.writer` quoting/escaping.
Parsed cells, order, duplicates and empty strings are preserved through the
mapping. Original bytes, BOM, quoting style and record line endings are not
preserved.

## 3. Current limits

- Up to 5 CSV files per run.
- Up to 10 columns and 100 data records per file, excluding the header.
- Up to 10 MiB per file and 131072 characters per field.
- Header-only CSVs are accepted; empty files or missing header records fail.
- Incorrect column counts, blank physical records and malformed CSV fail;
  records are not silently repaired or skipped.

CLI limits can be raised explicitly:

```bash
python3 -m sttm_sanitize --input reports --output larger-output --max-files 20 --max-fields 50 --max-rows 10000
```

`--max-file-bytes` and `--max-field-chars` control the other limits. All limit
arguments must be positive integers. Parsed data and mappings are held in RAM;
raising limits increases resource use. Large-data optimization is not claimed.

## 4. Tokenization and verification

One bijective mapping covers every **non-empty** data value within a run:

```text
same parsed string → same token
other parsed string → other token
empty string → empty string
```

Tokens use `v_` followed by 32 hexadecimal characters from
`secrets.token_hex(16)`. Collisions are checked and retried; original values are
not hashed to generate tokens. There is no encryption key or encryption.
Report names become `ds_001.csv`, and headers become `f_001`, `f_002`, etc. by
position. Duplicate/empty headers are recorded by index. Files sharing a
basename still receive separate dataset IDs. Absolute input paths are not
stored in the glossary.

Values are not trimmed, case-folded, parsed as numbers or Unicode-normalized.
`001`, `1`, `1.0`, `NULL`, `null` and ` ` are distinct strings. CSV quoting is
syntax: quoted and unquoted cells with the same parsed content share a token.
Empty strings remain empty. This CSV contract does not distinguish a typed
null from an empty string.

Before publishing output, the tool reads back the serialized ZIP and JSON to
verify:

- The ZIP contains exactly the allowed sanitized CSVs and no glossary.
- The mapping is bijective and covers all non-empty values.
- Every recovered cell matches the parsed input exactly.
- Headers, row order, widths, counts, duplicates and empty cells match.
- Input snapshot and sanitized CSV SHA-256 hashes match; input hashes stay local.

Verification failure prevents creation of the destination directory. I/O errors
or cancellation during publication may leave an incomplete directory.
**Use only output from a run that prints `PASS` and exits with code 0.**
Recovery files are written first and the upload ZIP last.

## 5. Upload and recovery glossary

1. Upload **only** `UPLOAD_reports.zip`.
2. Keep `glossary.json` private on your machine. Never upload the whole output
   directory, glossary or source ZIP as report input.
3. Store the glossary securely for as long as you need to recover original values.

The glossary records the reverse mapping, original headers and input basenames.
See [docs/GLOSSARY.md](docs/GLOSSARY.md) for its structure. The CLI does not
provide a recover/view command or export restored raw reports.

## 6. Privacy

See [PRIVACY.md](PRIVACY.md). The runtime has no networking, telemetry,
auto-update, API upload, cookies, browser storage or subprocess execution.
Input files are not modified. Handled errors/progress do not print cell values,
headers or absolute input paths. Output paths are printed so you can identify
what to upload and retain.

The glossary is plaintext JSON containing original values, filenames and
headers. Anyone with it can recover the data. This is **reversible tokenization,
not encryption or full anonymization**. Frequencies, equality, row/column counts,
order and relationships remain visible. Keep recovery material private and
apply your own retention policy. The tool has no remote backup. Python does not
guarantee secure memory wiping.

## 7. Validate the source

```bash
python3 -m unittest discover -s tests -v
python3 -m sttm_sanitize --help
```

Tests cover quoting, multiline cells, Unicode, empty/duplicate values,
cross-file equality, collisions, malformed CSV, limits, no-overwrite behavior,
serialized-output verification and a CLI subprocess with socket/DNS blocked.
Only synthetic examples and fixtures are included.
See [docs/VALIDATION.md](docs/VALIDATION.md) for executed checks and limits.

Source: https://github.com/buihoanghai/sttm-sanitize.
No license has been selected. Native binaries have not been built.
Windows/macOS execution has not been verified.
