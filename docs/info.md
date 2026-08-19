## How it works

FO backend of ML-KEM decapsulation. Two-pass streaming architecture:
ByteDecode -> decompress (pass 1), then re-stream -> compress and compare
in the coefficient domain (pass 2). ByteEncode is eliminated (bijection).
Independent coefficient-count integrity check drives implicit rejection
(motivated by CVE-2026-10097 / CVE-2026-6330). Q=3329 hardwired; no
generic multiplier/divider. Supports ML-KEM 512/768/1024 via uio[5:4].

## How to test

Drive `ui_in` with ciphertext bytes, pulse `wr`/`start`/`rd` on `uio_in`,
select the parameter set on `uio_in[5:4]` and pass on `uio_in[3]`.
Read result in S_DONE on `uo_out`: bit0 = MATCH, bit1 = FAULT.

## External hardware

None. Companion tile provides NTT/INTT and modular arithmetic.
