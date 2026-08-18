# Compact Fault-Aware FO Verification for ML-KEM

## Project scope

This project implements a compact hardware block for the Fujisaki–Okamoto (FO) verification back-end of ML-KEM decapsulation.

It is deliberately **not** a complete ML-KEM decapsulation engine. Keccak/SHAKE, complete re-encryption, key generation, and NTT/INTT are outside this tile. The external NTT/re-encryption processing is treated as a host-side datapath.

## Current Architecture-G baseline

The current repository baseline uses an 8-bit streaming interface and a sequential, constant-latency datapath.

The design supports the public ML-KEM parameter sets 512, 768 and 1024 through a shared datapath.

### Pass 1

Ciphertext coefficients are unpacked and decompressed. The block then performs the modular processing needed for the FO back-end and reconstructs the message bits through the compression path.

### Pass 2

The original ciphertext is streamed again while regenerated ciphertext coefficients are supplied by the host-side re-encryption path. The DUT performs a coefficient-domain equality check and reports MATCH only when all expected coefficients agree.

## Architecture novelty

The implementation is based on a **divider-free and multiplier-free constant-q datapath** using q = 3329. Compression is implemented with restoring division by a constant, while decompression reuses the sequential arithmetic structure. No general-purpose multiplier, divider, shifted-q register, or polynomial memory is required.

The FO verification path also uses parameter-derived coefficient counting and a sticky mismatch state so an incomplete comparison is not silently treated as success.

The intended research contribution is the combination of:

- compact ML-KEM FO verification,
- constant-latency operation,
- divider-free compression/decompression hardware,
- parameter agility across ML-KEM-512/768/1024,
- explicit fault/incomplete-comparison detection,
- and an aggressive Tiny Tapeout area target.

## Current interface

The current baseline is the verified 8-bit streaming interface:

- `ui_in[7:0]`: input data byte
- `uio_in[0]`: WR pulse
- `uio_in[1]`: START pulse
- `uio_in[2]`: RD pulse
- `uio_in[3]`: PHASE (0 = pass 1, 1 = pass 2)
- `uio_in[5:4]`: parameter select (00 = 512, 01 = 768, 10 = 1024)
- `uio_out[6]`: BUSY
- `uio_out[7]`: FAULT status
- `uo_out[0]`: MATCH in DONE
- `uo_out[1]`: FAULT in DONE
- `uo_out[7:0]`: streamed data while output data is valid

The six-functional-pin redesign is a separate optimization target and is **not claimed as implemented in this baseline**.

## Verification

The repository testbench is designed to exercise:

- reset/start protocol,
- ML-KEM-512 pass-2 clean verification,
- ML-KEM-512 ciphertext tamper rejection,
- ML-KEM-768 clean verification,
- ML-KEM-1024 clean verification,
- compression wrap-boundary reference checks,
- decompression reference checks.

A Python golden model is used for the mathematical compression/decompression checks.

## Physical implementation targets

The project is intended for Tiny Tapeout/SKY130 and is being optimized for:

- fewer than 1000 cells under the agreed project gate metric,
- six-functional-pin final interface,
- clock-to-clock synchronous operation,
- zero setup and hold violations,
- zero max-capacitance violations,
- zero max-slew violations,
- clean DRC and LVS.

The current repository baseline is an 8-bit implementation used for physical optimization before the final six-pin interface is frozen.
