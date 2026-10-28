# Recovery glossary contract v1

The local plaintext glossary records the reverse token mapping and source
metadata. Keep it private. The CLI verifies cell recovery before publishing
output but does not provide a recovery command.

## JSON envelope

- `schema`: `sttm-sanitize.glossary.v1` (reject unsupported versions).
- `tool_version`: producer version.
- `scope_id`: independent random scope for this run.
- `equality`: exact decoded CSV string, empty string unchanged.
- `source_format`, `output_format`: parser/writer settings.
- `datasets`: ordered list of per-dataset metadata.
- `values`: object `{token: original_string}` for every non-empty data value.
- `verification`: local verification checks and status.

Per-dataset fields:

- `dataset_id`: `ds_001`, `ds_002`, ... scoped to this glossary.
- `sanitized_filename`: `ds_001.csv`.
- `original_filename`: basename only, may collide across datasets.
- `source_sha256`: exact source snapshot, local-only metadata.
- `sanitized_sha256`: exact CSV bytes inside upload archive.
- `row_count`: number of data records, excluding header.
- `fields`: ordered `{field_id, original_name}` entries.

Field IDs `f_001`, ... are scoped to a dataset and identified by position.
Identical original header names do not cause fields to be merged. Data values
are mapped globally across all datasets in the scope, not per field/dataset.

## Recovery boundaries

Use the glossary from the same run as the sanitized archive. Dataset IDs are
scoped to that run and are not globally unique. Resolve tokens by exact lookup
in `values`; an empty cell remains empty. Unknown tokens cannot be recovered
from this glossary. Restore headers by dataset and column position.

Original strings are untrusted data. Treat them as text, never executable
formulas, HTML, scripts or SQL. Reversing tokens recovers parsed cell strings;
it does not reproduce the original file bytes, quoting or line endings.
