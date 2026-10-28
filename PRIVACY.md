# Data handling — v0.1.0

## What is read

Only selected CSVs (or CSV files directly inside selected folders), in-memory
CSV cells and input basenames. No home-directory scan, hidden-file scan, account
lookup, browser access, credentials, clipboard or environment collection.

## What is written

A private temporary staging directory under the chosen output parent, then a
new output folder containing the upload ZIP, plaintext glossary and guide.
Temporary staging is cleaned on normal exit/handled errors. Abrupt process or
OS failure can leave staging data: treat it as private and remove it locally.

On POSIX, output directories are mode 0700 and files 0600. Windows access is
controlled by the destination folder's ACL; Unix permission bits do not provide
an equivalent Windows guarantee. Use an output folder in your private profile,
not a shared/synced directory if you do not intend that service to receive it.

## What leaves the device

The program contains no network code, telemetry, AI calls, automatic upload,
update check, crash reporting or runtime subprocess. It runs without Internet.
Only an explicit user action outside this tool uploads a file. Python itself,
the terminal, OS/cloud sync, third-party software are outside this program's no-collection claim.

## Glossary and limits of protection

`glossary.json` contains original values, filenames and headers. It is not
encrypted and has no key. It must not be uploaded or committed to GitHub.
Distinct non-empty cell strings map bijectively to random tokens inside a scope;
empty strings remain empty. Equality, repetitions, shape, row order and relations
remain visible. This is reversible tokenization, not anonymous data.

No business semantics, classification, numeric processing, null inference or
field-role profiling is performed. CSV parsing is the identity boundary.

## Inspection

Review `sttm_sanitize/core.py` and `cli.py`. Runtime uses Python's standard
library only. Run all tests offline, including the network-blocked CLI test.
The no-network test covers the tested command paths; it is not a formal proof
against a malicious Python installation or modified binary/source.

## Errors and retention

Input cell values, headers and input names are not printed in handled errors.
The app has no log files. Output locations and aggregate counts are printed.
There is no secure-erasure guarantee for RAM, temporary files, filesystem
journals, OS backups or deleted files. Keep recovery material private for as
long as you need recovery, and delete it using your own retention policy.
