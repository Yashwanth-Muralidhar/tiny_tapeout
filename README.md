# Compact Fault-Aware FO Verification for ML-KEM

Tiny Tapeout project for a compact FO-verification back-end of ML-KEM decapsulation.

## Current repository baseline

- Top module: `tt_um_vinayaka_pqc_fo`
- RTL: `src/project.v`
- Tests: `test/test.py`
- Testbench: `test/tb.v`
- Test Makefile: `test/Makefile`
- Project metadata: `info.yaml`
- Datasheet text: `docs/info.md`

The current RTL is the Architecture-G/v7 8-bit interface baseline. The six-functional-pin version remains a separate final optimization step.

## Scope

The block focuses on the FO verification back-end of ML-KEM decapsulation. Keccak/SHAKE, complete re-encryption, and NTT/INTT are external to this small tile.
