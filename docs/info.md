# Tiny Tapeout project info
# top_module MUST exactly match the Verilog module name in src/project.v.
# (This mismatch — tt_um_vinayaka_pqc_fo_v7 vs tt_um_vinayaka_pqc_fo — was
# the root cause of the 43-pin LEF/GDS precheck failures earlier.)

project:
  title:        "Vinayaka PQC-FO: ML-KEM Field-Operation Engine"
  author:       "CHANGE_ME"
  discord:      "CHANGE_ME"
  description: >
    Streaming ML-KEM (512/768/1024) coefficient unpack/decompress engine
    with hardware auxiliary-reference coefficient verification and
    cumulative mismatch (MATCH/FAULT) detection.
  language:     "Verilog"
  clock_hz:     50000000   # 20 ns CLOCK_PERIOD in config.json = 50 MHz

  # top_module must match `module tt_um_vinayaka_pqc_fo` in src/project.v
  top_module:   "tt_um_vinayaka_pqc_fo"

  source_files:
    - "project.v"

  # protocol (uio_in bit layout, for reference / README):
  #   uio_in[0] wr, uio_in[1] start, uio_in[2] rd, uio_in[3] phase,
  #   uio_in[5:4] param (0=ML-KEM-512, 1=768, 2=1024)

pinout:
  ui_in:
    - "ciphertext/plaintext byte in (wr-strobed)"
    - ""
    - ""
    - ""
    - ""
    - ""
    - ""
    - ""
  uo_out:
    - "output byte / done status bit0 (MATCH)"
    - "done status bit1 (FAULT)"
    - ""
    - ""
    - ""
    - ""
    - ""
    - ""
  uio_in:
    - "wr strobe"
    - "start strobe"
    - "rd strobe"
    - "phase select"
    - "param[0]"
    - "param[1]"
    - ""
    - ""
  uio_out:
    - ""
    - ""
    - ""
    - ""
    - ""
    - ""
    - "busy"
    - "done_fault (at S_DONE)"

# Set to true only after the full cocotb suite (test.py) passes and the
# GDS precheck (pin/DRC/LVS/antenna) is clean end-to-end.
yaml_version: 6
