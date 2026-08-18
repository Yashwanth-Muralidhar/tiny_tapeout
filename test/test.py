# SPDX-License-Identifier: Apache-2.0
"""Tiny Tapeout cocotb regression for tt_um_vinayaka_pqc_fo.

v4 fix: keep the original two-byte auxiliary handshake. After a ciphertext
write, pulse_wr() waits through the UNP transition, so the pass-2 RTL is
already in S_RXA when send_aux() starts. A BUSY-edge detector is not valid
because the BUSY-high interval can occur entirely inside pulse_wr().

Architecture-G/v7-compatible regression.

Important parameter correction:
ML-KEM-512:  du=10, dv=4,  c1=640 bytes,  c2=128 bytes
ML-KEM-768:  du=10, dv=4,  c1=960 bytes,  c2=128 bytes
ML-KEM-1024: du=11, dv=5,  c1=1408 bytes, c2=160 bytes

The previous test used du=11,dv=5 for ML-KEM-768. That does not match
the RTL's parameter table or the ML-KEM parameter set represented by the
current Architecture-G design.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

Q = 3329
CLOCK_NS = 10

PARAMS = {
    0: dict(name="ML-KEM-512",  du=10, dv=4, split=512,  n_tot=768),
    1: dict(name="ML-KEM-768",  du=10, dv=4, split=768,  n_tot=1024),
    2: dict(name="ML-KEM-1024", du=11, dv=5, split=1024, n_tot=1280),
}


def compress(x, d):
    return (((x << d) + (Q // 2)) // Q) & ((1 << d) - 1)


def decompress(y, d):
    return ((y * Q) + (1 << (d - 1))) >> d


def pack_coeffs(coeffs, d):
    out = bytearray()
    acc = 0
    nbits = 0
    mask = (1 << d) - 1

    for c in coeffs:
        assert 0 <= c <= mask
        acc |= c << nbits
        nbits += d
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8

    assert nbits == 0
    return bytes(out)


def set_uio(dut, wr=0, start=0, rd=0, phase=0, param=0):
    dut.uio_in.value = (
        ((param & 3) << 4)
        | ((phase & 1) << 3)
        | ((rd & 1) << 2)
        | ((start & 1) << 1)
        | (wr & 1)
    )


def busy(dut):
    return (int(dut.uio_out.value) >> 6) & 1


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    set_uio(dut)
    dut.rst_n.value = 0
    await Timer(50, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def reset_dut(dut):
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def pulse_start(dut, param, phase):
    set_uio(dut, start=1, phase=phase, param=param)
    await RisingEdge(dut.clk)
    set_uio(dut, phase=phase, param=param)
    await RisingEdge(dut.clk)


async def pulse_wr(dut, value):
    dut.ui_in.value = value & 0xFF
    set_uio(dut, wr=1)
    await RisingEdge(dut.clk)
    set_uio(dut)
    await RisingEdge(dut.clk)


async def wait_ready(dut, limit=30000):
    """Wait for a ciphertext-byte input state."""
    for _ in range(limit):
        if not busy(dut):
            return
        await RisingEdge(dut.clk)
    raise AssertionError("Timeout waiting for ciphertext input state")


async def send_aux(dut, coeff):
    """Send the two-byte regenerated coefficient.

    Do not wait on BUSY here. After pulse_wr() returns, the RTL has already
    advanced from S_RXC through S_UNP/S_OUT into S_RXA for the pass-2 path.
    Both S_RXC and S_RXA expose BUSY=0, so trying to infer S_RXA from BUSY
    after the write can deadlock by missing the short BUSY-high interval.
    """
    assert 0 <= coeff < Q
    await pulse_wr(dut, coeff & 0xFF)
    await pulse_wr(dut, (coeff >> 8) & 0x0F)


async def wait_done(dut, limit=100000):
    stable = None
    for _ in range(limit):
        await RisingEdge(dut.clk)
        if not busy(dut):
            v = int(dut.uo_out.value) & 0x3
            if stable == v:
                return v
            stable = v
        else:
            stable = None
    raise AssertionError("Timeout waiting for DONE")


def make_case(param, seed, tamper_index=None):
    p = PARAMS[param]
    rng = random.Random(seed)

    regenerated = [rng.randrange(Q) for _ in range(p["n_tot"])]

    enc = []
    for i, x in enumerate(regenerated):
        d = p["du"] if i < p["split"] else p["dv"]
        enc.append(compress(x, d))

    if tamper_index is not None:
        assert 0 <= tamper_index < p["n_tot"]
        d = p["du"] if tamper_index < p["split"] else p["dv"]
        enc[tamper_index] ^= 1
        enc[tamper_index] &= (1 << d) - 1

    c1 = pack_coeffs(enc[:p["split"]], p["du"])
    c2 = pack_coeffs(enc[p["split"]:], p["dv"])
    ciphertext = c1 + c2

    expected_c1_len = p["split"] * p["du"] // 8
    expected_c2_len = (p["n_tot"] - p["split"]) * p["dv"] // 8
    assert len(c1) == expected_c1_len
    assert len(c2) == expected_c2_len

    return ciphertext, regenerated


async def run_pass2(dut, param, seed, tamper_index=None):
    p = PARAMS[param]
    ciphertext, regenerated = make_case(param, seed, tamper_index)

    await pulse_start(dut, param, phase=1)

    host_acc = 0
    host_bits = 0
    coeff_idx = 0

    for byte in ciphertext:
        # Service coefficients already complete before accepting another byte.
        while coeff_idx < p["n_tot"]:
            d = p["du"] if coeff_idx < p["split"] else p["dv"]
            if host_bits < d:
                break

            host_acc >>= d
            host_bits -= d
            await send_aux(dut, regenerated[coeff_idx])
            coeff_idx += 1

        await wait_ready(dut)
        await pulse_wr(dut, byte)

        host_acc |= byte << host_bits
        host_bits += 8

        # Service all coefficients completed by this byte.
        while coeff_idx < p["n_tot"]:
            d = p["du"] if coeff_idx < p["split"] else p["dv"]
            if host_bits < d:
                break

            host_acc >>= d
            host_bits -= d
            await send_aux(dut, regenerated[coeff_idx])
            coeff_idx += 1

    assert coeff_idx == p["n_tot"]
    assert host_bits == 0

    result = await wait_done(dut)
    match = bool(result & 1)
    fault = bool(result & 2)

    expected = tamper_index is None

    assert match == expected, (
        f"{p['name']}: expected MATCH={expected}, "
        f"got uo_out[1:0]={result:02b}"
    )
    assert not fault, f"{p['name']}: unexpected FAULT"


@cocotb.test()
async def test_reset_and_start(dut):
    await start_clock(dut)
    await pulse_start(dut, 0, 1)
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_mlkem512_clean_and_tamper(dut):
    await start_clock(dut)
    await run_pass2(dut, 0, 0x512A)

    await reset_dut(dut)
    await run_pass2(dut, 0, 0x512A, tamper_index=767)


@cocotb.test()
async def test_mlkem768_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 1, 0x768A)


@cocotb.test()
async def test_mlkem1024_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 2, 0x1024A)


@cocotb.test()
async def test_compression_boundaries(dut):
    boundaries = {1: 2497, 4: 3225, 5: 3277, 10: 3328}

    for d, x in boundaries.items():
        assert compress(x, d) == 0
        assert compress(x - 1, d) != 0

    assert all(compress(x, 11) != 0 for x in range(1, Q))


@cocotb.test()
async def test_decompression_reference_ranges(dut):
    for d in (4, 5, 10, 11):
        for y in range(1 << d):
            x = decompress(y, d)
            assert 0 <= x < Q
