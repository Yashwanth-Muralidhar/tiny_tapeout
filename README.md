# Compact Fault-Aware FO Verification for ML-KEM

Tiny Tapeout project implementing a compact, constant-latency, divider-free hardware block for the FO verification back-end of ML-KEM decapsulation.

## Repository layout

- `src/project.v` — Tiny Tapeout top-level RTL (`tt_um_vinayaka_pqc_fo`)
- `test/` — cocotb verification
- `docs/info.md` — project datasheet text
- `info.yaml` — Tiny Tapeout project metadata

## Design scope

This is not a full ML-KEM implementation. Keccak/SHAKE, complete re-encryption and the NTT are outside this tile.

The hardware focuses on the FO verification back-end: coefficient decoding/decompression, modular processing, constant-time compression/comparison, and parameter-derived fault detection.

## Current development target

The current Architecture-G RTL is the physical optimization baseline. The final target is a sub-1000-gate, six-functional-pin, clock-to-clock implementation with clean STA, max-cap/max-slew, DRC and LVS.

## License

Apache-2.0
