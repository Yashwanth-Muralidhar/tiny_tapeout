# Compact Fault-Aware FO Verification for ML-KEM

## Overview

This project implements a compact hardware block for the **Fujisaki–Okamoto (FO) verification back-end of ML-KEM decapsulation**.

The design is deliberately scoped below a complete ML-KEM decapsulation engine. It does not implement Keccak/SHAKE, key generation, complete re-encryption, or the NTT butterfly. The NTT side is treated as an external datapath.

The hardware is designed around three constraints:

- small ASIC area suitable for Tiny Tapeout,
- constant-latency operation determined by the public ML-KEM parameter set and streaming protocol,
- fault-aware ciphertext verification.

## How it works

The current verified Architecture-G baseline uses an 8-bit streaming interface.

### Pass 1

1. Ciphertext bytes are received and unpacked into ML-KEM coefficients.
2. Coefficients are decompressed using a sequential constant-`q` datapath with `q = 3329`.
3. The externally supplied auxiliary polynomial result is combined with the decompressed value using modular subtraction.
4. The result is compressed to recover the message bits.

### Pass 2

1. The original ciphertext is streamed again.
2. Regenerated ciphertext coefficients are supplied by the host-side re-encryption path.
3. Both sides are unpacked into the same coefficient representation.
4. A sticky mismatch accumulator performs constant-time comparison.
5. The coefficient count is checked against the parameter-derived expected count.
6. The block reports `MATCH` only when all compared coefficients match and the expected number of coefficients has been consumed; incomplete processing raises `FAULT`.

## Architecture

The compression/decompression datapath is intentionally divider-free and multiplier-free.

The implementation uses:

- a shared sequential accumulator/remainder datapath,
- constant `q = 3329`,
- restoring division for compression,
- no polynomial memory,
- no general-purpose multiplier,
- no general-purpose divider,
- parameter selection for ML-KEM-512, ML-KEM-768 and ML-KEM-1024.

The current physical baseline has already been taken through SKY130 synthesis and physical implementation experiments. Further work is focused on the final Tiny Tapeout interface, area margin, and electrical signoff.

## Fault-awareness

The architecture includes a parameter-derived coefficient-count check so that premature or incomplete comparison can be detected rather than silently treated as a successful verification.

This is intended to address the broader implementation class of incomplete ciphertext-comparison failures. The project does **not** claim to cryptographically or universally "fix" any particular CVE.

## How to test

The design is clock-synchronous.

The current baseline uses:

- `ui_in[7:0]` for streamed input data,
- `uio_in[5:0]` for write/start/read/phase/parameter controls,
- `uio_out[7:6]` for status,
- `uo_out[7:0]` for streamed output/status.

The cocotb testbench should verify, at minimum:

- ML-KEM-512,
- ML-KEM-768,
- ML-KEM-1024,
- pass-1 functional correctness against the Python golden model,
- pass-2 equality detection,
- modified ciphertext detection,
- incomplete-stream / forced-completion fault detection,
- constant latency for fixed public parameters.

## External hardware

No external accelerator or memory is required for the RTL block itself.

The host-side test environment supplies streamed ciphertext/auxiliary data and can perform the portions of ML-KEM processing intentionally kept outside this small tapeout block, such as the external NTT/re-encryption path.

## Current status

The current repository should be treated as the **physical-optimization baseline**.

The hard project targets are:

- fewer than 1000 gates/cells according to the agreed project metric,
- six-functional-pin final interface,
- clock-to-clock synchronous operation,
- zero setup/hold violations,
- zero max-cap violations,
- zero max-slew violations,
- DRC clean,
- LVS clean,
- Tiny Tapeout-compatible GDS.

The six-functional-pin redesign is not claimed here until its RTL and verification are frozen.
