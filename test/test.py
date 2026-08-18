# SPDX-FileCopyrightText: (c) 2026 H Vinayaka
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

Q = 3329

PARAMS = {
    0: dict(k=2, du=10, dv=4, c1=640,  cx=768,  n=768),
    1: dict(k=3, du=10, dv=4, c1=960,  cx=1088, n=1024),
    2: dict(k=4, du=11, dv=5, c1=1408, cx=1568, n=1280),
}


# ---------------- reference model ----------------

def decompress(y, d):
    """FIPS 203 Decompress_d: round(y*q / 2^d)."""
    return (y * Q + (1 << (d - 1))) >> d


def compress(x, d):
    """FIPS 203 Compress_d: round(2^d * x / q) mod 2^d."""
    return ((x << d) + (Q >> 1)) // Q % (1 << d)


def pack(coeffs, d):
    """Little-endian bit packing, byte aligned at end of stream."""
    bits = 0
    nb = 0
    out = bytearray()

    for c in coeffs:
        bits |= (c & ((1 << d) - 1)) << nb
        nb += d

        while nb >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            nb -= 8

    if nb:
        out.append(bits & 0xFF)

    return bytes(out)


def build_ciphertext(p, seed=1):
    """Return (ct_bytes, u_coeffs, v_coeffs)."""

    nu = 256 * p["k"]

    rnd = seed
    u = []
    v = []

    for _ in range(nu):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        u.append(rnd % (1 << p["du"]))

    for _ in range(256):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        v.append(rnd % (1 << p["dv"]))

    ct = pack(u, p["du"]) + pack(v, p["dv"])

    assert len(ct) == p["cx"], (
        f"Ciphertext length mismatch: "
        f"{len(ct)} != {p['cx']}"
    )

    return ct, u, v


# ---------------- bus driver ----------------

class Dut:

    def __init__(self, dut, pr, phase):
        self.dut = dut

        # Keep parameter + phase permanently encoded.
        #
        # uio_in:
        #   [0] = WR
        #   [1] = START
        #   [2] = RD
        #   [3] = PHASE
        #   [5:4] = PARAMETER
        self.ctrl = (pr << 4) | (phase << 3)

    async def _pulse(self, bit):

        self.dut.uio_in.value = (
            self.ctrl | (1 << bit)
        )

        await ClockCycles(self.dut.clk, 1)

        # IMPORTANT:
        # Do NOT clear phase/parameter after the pulse.
        self.dut.uio_in.value = self.ctrl

        await ClockCycles(self.dut.clk, 1)

    async def start(self):
        await self._pulse(1)

    async def write(self, byte):

        self.dut.ui_in.value = byte & 0xFF

        await self._pulse(0)

    async def read(self):

        val = int(self.dut.uo_out.value)

        await self._pulse(2)

        return val

    def busy(self):

        return (
            int(self.dut.uio_out.value) >> 6
        ) & 1


async def reset(dut):

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0

    dut.rst_n.value = 0

    await ClockCycles(dut.clk, 10)

    dut.rst_n.value = 1

    await ClockCycles(dut.clk, 5)


# ---------------- wait helpers ----------------

async def wait_ciphertext_ready(dut, limit=30000):
    """
    Wait until the DUT is ready for a ciphertext byte.

    In the repaired RTL:
        BUSY=0 -> S_RXC / externally writable state
        BUSY=1 -> processing / S_RXA

    Therefore BUSY is safe for ciphertext readiness.
    """

    for _ in range(limit):

        if not d_busy(dut):
            return

        await ClockCycles(dut.clk, 1)

    raise AssertionError(
        "Timeout waiting for ciphertext input state"
    )


def d_busy(dut):

    return (
        int(dut.uio_out.value) >> 6
    ) & 1


async def send_aux(dut, coeff):
    """
    Send one regenerated 12-bit coefficient.

    IMPORTANT:

    We do NOT wait for BUSY here.

    After the ciphertext byte that completed the coefficient has
    finished its write pulse, the repaired RTL has progressed:

        S_RXC -> S_UNP -> S_RXA

    and S_RXA accepts the two auxiliary bytes.
    """

    assert 0 <= coeff < Q

    # Low 8 bits
    dut.ui_in.value = coeff & 0xFF

    # WR pulse while preserving phase/parameter.
    # The current phase is recovered from uio_in.
    current_ctrl = int(dut.uio_in.value) & 0xF8

    dut.uio_in.value = current_ctrl | 1

    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = current_ctrl

    await ClockCycles(dut.clk, 1)

    # High 4 bits
    dut.ui_in.value = (coeff >> 8) & 0x0F

    dut.uio_in.value = current_ctrl | 1

    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = current_ctrl

    await ClockCycles(dut.clk, 1)


async def wait_aux_processing(dut, width, limit=30000):
    """
    Wait for the DUT to finish processing one auxiliary coefficient.

    In pass 2:

        S_RXA
          -> S_CLD
          -> S_CMP
          -> S_ACC
          -> S_UNP
          -> S_RXA

    The compression loop takes width+1 cycles.

    We use a conservative width-dependent delay instead of trying to
    detect S_RXA through BUSY, because S_RXA itself has BUSY=1 in the
    repaired RTL.
    """

    # Conservative processing interval:
    #
    # S_CLD      : 1
    # S_CMP      : width + 1
    # S_ACC      : 1
    # S_UNP      : 1
    #
    # Add margin for nonblocking state transitions.
    cycles = width + 6

    await ClockCycles(dut.clk, cycles)


# ---------------- tests ----------------

@cocotb.test()
async def test_reset_start(dut):

    """Reset leaves the FSM idle and start is accepted."""

    cocotb.start_soon(
        Clock(
            dut.clk,
            20,
            units="ns"
        ).start()
    )

    await reset(dut)

    assert int(dut.uo_out.value) == 0, (
        "uo_out must be 0 after reset"
    )

    d = Dut(dut, 0, 0)

    await d.start()

    await ClockCycles(dut.clk, 5)

    dut._log.info(
        "start accepted, uio_out=%s"
        % dut.uio_out.value
    )


@cocotb.test()
async def test_reference_model(dut):

    """Pure software check of Compress/Decompress."""

    for d in (4, 5, 10, 11):

        for y in range(1 << d):

            x = decompress(y, d)

            assert 0 <= x < Q, (
                f"decompress out of range "
                f"d={d} y={y} x={x}"
            )

            assert compress(x, d) == y, (
                f"roundtrip fail d={d} y={y}"
            )

    dut._log.info(
        "reference model round trip OK "
        "for d=4,5,10,11"
    )


# ---------------- pass-2 verification ----------------

async def run_verify(dut, pr, tamper=False):

    """
    Pass-2 verification.

    The host streams the ciphertext and supplies the regenerated
    coefficient corresponding to every decoded ciphertext coefficient.

    Crucially, auxiliary scheduling is driven by the HOST'S copy of
    the ciphertext bit unpacker rather than by ambiguous BUSY polling.
    """

    p = PARAMS[pr]

    ct, u, v = build_ciphertext(
        p,
        seed=pr + 1
    )

    # ------------------------------------------------------------
    # Start clock
    # ------------------------------------------------------------

    # Clock is normally started by the individual cocotb test.
    # Keep this guard-compatible with the original structure.
    #
    # reset() is still performed here because every run is independent.
    await reset(dut)

    # ------------------------------------------------------------
    # Pass 2
    # ------------------------------------------------------------

    d = Dut(
        dut,
        pr,
        1
    )

    await d.start()

    # ------------------------------------------------------------
    # Regenerated auxiliary coefficients
    # ------------------------------------------------------------

    aux = (
        [decompress(c, p["du"]) for c in u]
        +
        [decompress(c, p["dv"]) for c in v]
    )

    if tamper:
        aux[0] = (aux[0] + 1) % Q

    # ------------------------------------------------------------
    # Host-side copy of the DUT bit unpacker
    # ------------------------------------------------------------

    host_acc = 0
    host_bits = 0

    ai = 0

    u_coeffs = 256 * p["k"]

    # ------------------------------------------------------------
    # Stream ciphertext
    # ------------------------------------------------------------

    for byte_index, byte in enumerate(ct):

        # The DUT must be ready for a ciphertext byte.
        await wait_ciphertext_ready(dut)

        # Send exactly one ciphertext byte.
        await d.write(byte)

        # Mirror:
        #
        #     buf_r |= byte << nbits
        #
        host_acc |= byte << host_bits
        host_bits += 8

        # --------------------------------------------------------
        # Determine whether this byte completed coefficient(s).
        # --------------------------------------------------------

        while ai < len(aux):

            # Determine coefficient width.
            if ai < u_coeffs:
                width = p["du"]
            else:
                width = p["dv"]

            # Not enough bits yet for this coefficient.
            if host_bits < width:
                break

            # ----------------------------------------------------
            # Remove coefficient from host-side bit stream.
            # ----------------------------------------------------

            coeff_bits = host_acc & ((1 << width) - 1)

            host_acc >>= width
            host_bits -= width

            # The actual ciphertext coefficient should equal
            # the coefficient generated in build_ciphertext().
            expected_coeff = (
                u[ai]
                if ai < u_coeffs
                else v[ai - u_coeffs]
            )

            assert coeff_bits == expected_coeff, (
                f"Host unpack mismatch at coefficient {ai}: "
                f"got {coeff_bits}, "
                f"expected {expected_coeff}"
            )

            # ----------------------------------------------------
            # Send regenerated auxiliary coefficient.
            # ----------------------------------------------------

            await send_aux(
                dut,
                aux[ai]
            )

            ai += 1

            # ----------------------------------------------------
            # If another complete coefficient is already buffered,
            # the DUT must process the current auxiliary value first.
            # ----------------------------------------------------

            if ai < len(aux):

                if ai < u_coeffs:
                    next_width = p["du"]
                else:
                    next_width = p["dv"]

                if host_bits >= next_width:

                    # Wait for current auxiliary processing.
                    await wait_aux_processing(
                        dut,
                        width
                    )

                else:
                    # No second coefficient is available yet.
                    # The DUT will eventually return to S_RXC.
                    break

    # ------------------------------------------------------------
    # Final checks
    # ------------------------------------------------------------

    assert ai == len(aux), (
        f"Only supplied {ai}/{len(aux)} "
        "auxiliary coefficients"
    )

    assert host_bits == 0, (
        f"Host unpacker still contains "
        f"{host_bits} bits"
    )

    # Wait for final coefficient processing.
    #
    # The final auxiliary coefficient may still be inside:
    #
    # S_CLD -> S_CMP -> S_ACC -> S_UNP -> S_FIN -> S_DONE
    #
    final_width = p["dv"]

    await ClockCycles(
        dut.clk,
        final_width + 10
    )

    # Give S_FIN/S_DONE additional margin.
    await ClockCycles(
        dut.clk,
        20
    )

    res = int(dut.uo_out.value)

    match = res & 1
    fault = (res >> 1) & 1

    return match, fault


# ---------------- ML-KEM-512 clean ----------------

@cocotb.test()
async def test_mlkem512_clean(dut):

    match, fault = await run_verify(
        dut,
        0,
        tamper=False
    )

    dut._log.info(
        f"ML-KEM-512 clean: "
        f"MATCH={match} FAULT={fault}"
    )

    assert match == 1, (
        "ML-KEM-512 clean must report MATCH=1"
    )


# ---------------- ML-KEM-512 tamper ----------------

@cocotb.test()
async def test_mlkem512_tamper(dut):

    match, fault = await run_verify(
        dut,
        0,
        tamper=True
    )

    dut._log.info(
        f"ML-KEM-512 tamper: "
        f"MATCH={match} FAULT={fault}"
    )

    assert match == 0, (
        "Tampered ciphertext must not report MATCH"
    )


# ---------------- ML-KEM-768 ----------------

@cocotb.test()
async def test_mlkem768_clean(dut):

    match, fault = await run_verify(
        dut,
        1,
        tamper=False
    )

    dut._log.info(
        f"ML-KEM-768 clean: "
        f"MATCH={match} FAULT={fault}"
    )

    assert match == 1, (
        "ML-KEM-768 clean must report MATCH=1"
    )


# ---------------- ML-KEM-1024 ----------------

@cocotb.test()
async def test_mlkem1024_clean(dut):

    match, fault = await run_verify(
        dut,
        2,
        tamper=False
    )

    dut._log.info(
        f"ML-KEM-1024 clean: "
        f"MATCH={match} FAULT={fault}"
    )

    assert match == 1, (
        "ML-KEM-1024 clean must report MATCH=1"
    )
