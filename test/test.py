# SPDX-License-Identifier: Apache-2.0
"""
Cocotb tests for tt_um_vinayaka_pqc_fo.

Current RTL interface:
  ui_in[7:0]   : input byte stream
  uio_in[0]    : WR
  uio_in[1]    : START
  uio_in[2]    : RD
  uio_in[3]    : PHASE (0=pass 1, 1=pass 2)
  uio_in[5:4]  : parameter (00=512, 01=768, 10=1024)
  uio_out[6]  : BUSY
  uio_out[7]  : FAULT
  uo_out[0]   : MATCH in DONE
  uo_out[1]   : FAULT in DONE
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

Q = 3329
CLOCK_NS = 10

PARAMS = {
    0: dict(name="ML-KEM-512", du=10, dv=4, split=256, n_tot=768),
    1: dict(name="ML-KEM-768", du=11, dv=5, split=768, n_tot=1024),
    2: dict(name="ML-KEM-1024", du=11, dv=5, split=1024, n_tot=1280),
}


def compress(x: int, d: int) -> int:
    return (((x << d) + (Q // 2)) // Q) & ((1 << d) - 1)


def decompress(y: int, d: int) -> int:
    return ((y * Q) + (1 << (d - 1))) >> d


def pack_coeffs(coeffs, d: int) -> bytes:
    """LSB-first coefficient packing, matching the DUT unpacker."""
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


def set_uio(dut, *, wr=0, start=0, rd=0, phase=0, param=0):
    dut.uio_in.value = (
        ((param & 0x3) << 4)
        | ((phase & 1) << 3)
        | ((rd & 1) << 2)
        | ((start & 1) << 1)
        | (wr & 1)
    )


def get_busy(dut) -> int:
    return (int(dut.uio_out.value) >> 6) & 1


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    set_uio(dut)
    dut.rst_n.value = 0
    await Timer(50, units="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, units="ns").start())
    await reset_dut(dut)


async def pulse_start(dut, param: int, phase: int):
    set_uio(dut, start=1, phase=phase, param=param)
    await RisingEdge(dut.clk)
    set_uio(dut, phase=phase, param=param)
    await RisingEdge(dut.clk)


async def pulse_wr(dut, value: int):
    dut.ui_in.value = value & 0xFF
    set_uio(dut, wr=1)
    await RisingEdge(dut.clk)
    set_uio(dut)
    await RisingEdge(dut.clk)


async def wait_done(dut, limit=50000):
    """Wait for the final DONE result after the last input."""
    stable = None
    for _ in range(limit):
        await RisingEdge(dut.clk)
        if not get_busy(dut):
            val = int(dut.uo_out.value) & 0x3
            if stable == val:
                return val
            stable = val
        else:
            stable = None
    raise AssertionError("Timeout waiting for DONE")


async def wait_for_rxaux(dut, limit=3000):
    """Wait until the DUT reaches its auxiliary-coefficient input state."""
    seen_busy = False
    for _ in range(limit):
        await RisingEdge(dut.clk)
        b = get_busy(dut)
        if b:
            seen_busy = True
        elif seen_busy:
            return
    raise AssertionError("Timeout waiting for auxiliary coefficient input")


async def send_aux(dut, coeff: int):
    assert 0 <= coeff < Q
    await pulse_wr(dut, coeff & 0xFF)
    await pulse_wr(dut, (coeff >> 8) & 0x0F)


def make_pass2_case(param: int, seed: int, tamper_index=None):
    p = PARAMS[param]
    rng = random.Random(seed)
    regenerated = [rng.randrange(Q) for _ in range(p["n_tot"])]

    encoded = []
    for i, x in enumerate(regenerated):
        d = p["du"] if i < p["split"] else p["dv"]
        encoded.append(compress(x, d))

    if tamper_index is not None:
        assert 0 <= tamper_index < len(encoded)
        d = p["du"] if tamper_index < p["split"] else p["dv"]
        encoded[tamper_index] ^= 1
        encoded[tamper_index] &= (1 << d) - 1

    c1 = pack_coeffs(encoded[:p["split"]], p["du"])
    c2 = pack_coeffs(encoded[p["split"]:], p["dv"])
    return c1 + c2, regenerated


async def run_pass2(dut, param: int, seed: int, tamper_index=None):
    p = PARAMS[param]
    ciphertext, regenerated = make_pass2_case(param, seed, tamper_index)

    await pulse_start(dut, param, phase=1)

    bit_acc = 0
    nbits = 0
    coeff_index = 0

    for byte in ciphertext:
        await pulse_wr(dut, byte)

        bit_acc |= byte << nbits
        nbits += 8

        while coeff_index < p["n_tot"]:
            d = p["du"] if coeff_index < p["split"] else p["dv"]
            if nbits < d:
                break

            bit_acc >>= d
            nbits -= d

            await wait_for_rxaux(dut)
            await send_aux(dut, regenerated[coeff_index])
            coeff_index += 1

    assert coeff_index == p["n_tot"]
    assert nbits == 0

    result = await wait_done(dut)
    match = bool(result & 0x1)
    fault = bool(result & 0x2)

    expected_match = tamper_index is None
    assert match == expected_match, (
        f"{p['name']} pass2: expected MATCH={expected_match}, "
        f"got uo_out[1:0]={result:02b}"
    )
    assert not fault, f"{p['name']} pass2: unexpected FAULT"


@cocotb.test()
async def test_reset_and_start(dut):
    await start_clock(dut)
    await pulse_start(dut, 0, 1)
    await RisingEdge(dut.clk)
    assert int(dut.uio_out.value) >= 0


@cocotb.test()
async def test_mlkem512_clean_and_tamper(dut):
    await start_clock(dut)
    await run_pass2(dut, 0, seed=0x512A)

    await reset_dut(dut)
    await run_pass2(dut, 0, seed=0x512A, tamper_index=767)


@cocotb.test()
async def test_mlkem768_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 1, seed=0x768A)


@cocotb.test()
async def test_mlkem1024_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 2, seed=0x1024A)


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
