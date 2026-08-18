## How it works

A divider-free, multiplier-free backend for the Fujisaki-Okamoto
re-encryption check in ML-KEM (Kyber) decapsulation. Two narrow
constant-Q engines share one datapath:

**Decompress** — a 23-bit accumulator computes `acc <- 2*acc + y_bit*Q`
over `d` cycles, yielding `y*Q`. The FIPS 203 rounding term `2^(d-1)`
is a single set bit, so the rounding adder collapses to a one-bit
increment: `x = acc[d+11:d] + acc[d-1]`.

**Compress** — a 12-bit remainder performs restoring division by the
same constant `Q` in `d+1` cycles, the last quotient bit serving as the
rounding bit.

`Q = 3329` appears in the netlist only as a hardwired constant. There is
no shifted copy, no multiplier, no divider, and no ciphertext memory:
the ciphertext is consumed as a stream. Latency depends only on the
public parameter set.

## How to test

Drive `ui_in` with ciphertext bytes and strobe `uio_in[0]` (wr).
Pulse `uio_in[1]` (start) to begin. Select the parameter set on
`uio_in[5:4]` (00=512, 01=768, 10=1024) and the pass on `uio_in[3]`
(0=decode, 1=verify). When `uio_in[6]` (BUSY) is low the core is
ready for the next byte. At end of stream `uo_out[0]`=MATCH and
`uo_out[1]`=FAULT.

## External hardware

None. A microcontroller or host FPGA streams the ciphertext bytes.
