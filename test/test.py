# SPDX-FileCopyrightText: (c) 2026 H Vinayaka
# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

Q = 3329

PARAMS = {
    0: dict(k=2, du=10, dv=4, c1=640,  cx=768,  n=768),   # ML-KEM-512
    1: dict(k=3, du=10, dv=4, c1=960,  cx=1088, n=1024),  # ML-KEM-768
    2: dict(k=4, du=11, dv=5, c1=1408, cx=1568, n=1280),  # ML-KEM-1024
}


# ---------------- reference model ----------------
def decompress(y, d):
    """FIPS 203 Decompress_d: round(y*q / 2^d)"""
    return (y * Q + (1 << (d - 1))) >> d


def compress(x, d):
    """FIPS 203 Compress_d: round(2^d * x / q) mod 2^d"""
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
    """Return (ct_bytes, u_coeffs, v_coeffs) for parameter dict p."""
    nu = 256 * p["k"]
    rnd = seed
    u, v = [], []
    for i in range(nu):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        u.append(rnd % (1 << p["du"]))
    for i in range(256):
        rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
        v.append(rnd % (1 << p["dv"]))
    ct = pack(u, p["du"]) + pack(v, p["dv"])
    assert len(ct) == p["cx"], f"{len(ct)} != {p['cx']}"
    return ct, u, v


# ---------------- bus driver ----------------
class Dut:
    def __init__(self, dut, pr, phase):
        self.dut = dut
        self.ctrl = (pr << 4) | (phase << 3)

    async def _pulse(self, bit):
        self.dut.uio_in.value = self.ctrl | (1 << bit)
        await ClockCycles(self.dut.clk, 1)
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
        return (int(self.dut.uio_out.value) >> 6) & 1


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


# ---------------- tests ----------------
@cocotb.test()
async def test_reset_start(dut):
    """Reset leaves the FSM idle and start is accepted."""
    cocotb.start_soon(Clock(dut.clk, 20, units="ns").start())
    await reset(dut)
    assert int(dut.uo_out.value) == 0, "uo_out must be 0 after reset"
    d = Dut(dut, 0, 0)
    await d.start()
    await ClockCycles(dut.clk, 5)
    dut._log.info("start accepted, uio_out=%s" % dut.uio_out.value)


@cocotb.test()
async def test_reference_model(dut):
    """Pure software check of Compress/Decompress round trip ranges."""
    for d in (4, 5, 10, 11):
        for y in range(1 << d):
            x = decompress(y, d)
            assert 0 <= x < Q, f"decompress out of range d={d} y={y} x={x}"
            assert compress(x, d) == y, f"roundtrip fail d={d} y={y}"
    dut._log.info("reference model round trip OK for d=4,5,10,11")


async def run_verify(dut, pr, tamper=False):
    """Pass-2 verify: stream ct, feed regenerated aux coeffs, check MATCH."""
    p = PARAMS[pr]
    ct, u, v = build_ciphertext(p, seed=pr + 1)

    cocotb.start_soon(Clock(dut.clk, 20, units="ns").start())
    await reset(dut)
    d = Dut(dut, pr, 1)
    await d.start()

    # aux stream = decompressed value of every coefficient, in order
    aux = [decompress(c, p["du"]) for c in u] + \
          [decompress(c, p["dv"]) for c in v]
    if tamper:
        aux[0] = (aux[0] + 1) % Q

    ai = 0
    for byte in ct:
        await d.write(byte)
        # after each ct byte the DUT may request aux words
        for _ in range(64):
            if d.busy():
                await ClockCycles(dut.clk, 1)
                continue
            break
        while ai < len(aux) and not d.busy():
            a = aux[ai]
            await d.write(a & 0xFF)
            await d.write((a >> 8) & 0x0F)
            ai += 1
            for _ in range(64):
                if d.busy():
                    await ClockCycles(dut.clk, 1)
                else:
                    break

    await ClockCycles(dut.clk, 200)
    res = int(dut.uo_out.value)
    return res & 1, (res >> 1) & 1


@cocotb.test()
async def test_mlkem512_clean(dut):
    match, fault = await run_verify(dut, 0, tamper=False)
    dut._log.info(f"ML-KEM-512 clean: MATCH={match} FAULT={fault}")


@cocotb.test()
async def test_mlkem512_tamper(dut):
    match, fault = await run_verify(dut, 0, tamper=True)
    dut._log.info(f"ML-KEM-512 tamper: MATCH={match} FAULT={fault}")
    assert match == 0, "tampered ciphertext must not report MATCH"


@cocotb.test()
async def test_mlkem768_clean(dut):
    match, fault = await run_verify(dut, 1, tamper=False)
    dut._log.info(f"ML-KEM-768 clean: MATCH={match} FAULT={fault}")


@cocotb.test()
async def test_mlkem1024_clean(dut):
    match, fault = await run_verify(dut, 2, tamper=False)
    dut._log.info(f"ML-KEM-1024 clean: MATCH={match} FAULT={fault}")
