# Validation scope

Run `python3 -m unittest discover -s tests -v` without installing packages.

Tests cover actual CSV parsing/writing and serialized ZIP/JSON readback. A
seeded randomized case checks equality partitions on generated cells, not only
that one example mapping is correct. A subprocess test blocks Python socket
creation and name resolution while running the complete CLI flow.

Tests intentionally do not claim:

- real customer-data validation;
- whole-workbook or byte-for-byte input recovery;
- Windows/macOS compatibility before execution there;
- absence of collection by the OS, Python distribution, modified source/binary
  or external software;
- protection after the plaintext glossary is disclosed.

Only synthetic examples are distributed. Runtime output and customer data must
never be committed into a public repository.

## Executed validation for this delivery

- Host: Linux, CPython 3.14.8 (2026-10-28).
- `python3 -m unittest discover -s tests -v`: 26 tests, PASS.
- CLI smoke run on two synthetic example CSVs: PASS; 8 data records, 34 cells,
  20 distinct non-empty values. Upload ZIP contains exactly two sanitized CSVs.
- Windows and macOS execution: NOT_RUN.
