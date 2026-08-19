# ML-KEM Decapsulation — Fujisaki-Okamoto Backend

Tiny Tapeout 1x1 implementation of `tt_um_vinayaka_pqc_fo`.

The RTL supports the Tiny Tapeout interface:
- `ui_in[7:0]`
- `uo_out[7:0]`
- `uio_in[7:0]`
- `uio_out[7:0]`
- `uio_oe[7:0]`
- `ena`
- `clk`
- `rst_n`

The hardening configuration uses a 1x1 Sky130 die:
161.00 um x 111.52 um.

This package contains the optimized RTL with the requested register-sharing and width reductions.
