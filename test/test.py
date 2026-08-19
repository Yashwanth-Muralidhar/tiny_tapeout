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
            out.append(acc & 0xff)
            acc >>= 8
            nbits -= 8
    assert nbits == 0
    return bytes(out)

def set_uio(dut, wr=0, start=0, rd=0, phase=0, param=0):
    dut.uio_in.value = (
        ((param & 3) << 4) |
        ((phase & 1) << 3) |
        ((rd & 1) << 2) |
        ((start & 1) << 1) |
        (wr & 1)
    )

def busy(dut):
    return (int(dut.uio_out.value) >> 6) & 1

def compare_outputs(dut, tag):
    pairs = [
        ("uo_out", int(dut.ref_uo_out.value), int(dut.opt_uo_out.value)),
        ("uio_out", int(dut.ref_uio_out.value), int(dut.opt_uio_out.value)),
        ("uio_oe", int(dut.ref_uio_oe.value), int(dut.opt_uio_oe.value)),
    ]
    for name, a, b in pairs:
        if a != b:
            raise AssertionError(
                f"{tag}: {name} mismatch ref=0x{a:02x} opt=0x{b:02x}"
            )

    # For this optimization, internal control/counter state should remain
    # identical. This catches a divergence before it becomes externally visible.
    common = ["st", "byte_cnt", "coef_cnt", "nbits", "bitk",
              "out_cnt", "aux_hi", "in_c2", "masm", "mcnt"]
    for sig in common:
        try:
            a = int(getattr(dut.ref, sig).value)
            b = int(getattr(dut.opt, sig).value)
        except Exception:
            continue
        if a != b:
            raise AssertionError(
                f"{tag}: internal {sig} mismatch ref={a} opt={b}"
            )

async def edge(dut, tag):
    await RisingEdge(dut.clk)
    compare_outputs(dut, tag)

async def pulse_start(dut, param, phase, tag):
    set_uio(dut, start=1, phase=phase, param=param)
    await edge(dut, tag)
    set_uio(dut, phase=phase, param=param)
    await edge(dut, tag)

async def pulse_wr(dut, value, tag):
    dut.ui_in.value = value & 0xff
    set_uio(dut, wr=1)
    await edge(dut, tag)
    set_uio(dut)
    await edge(dut, tag)

async def wait_ready(dut, tag, limit=40000):
    for _ in range(limit):
        compare_outputs(dut, tag)
        if not busy(dut):
            return
        await edge(dut, tag)
    raise AssertionError(f"{tag}: timeout waiting for input-ready")

async def send_aux(dut, coeff, tag):
    assert 0 <= coeff < Q
    await pulse_wr(dut, coeff & 0xff, tag)
    await pulse_wr(dut, (coeff >> 8) & 0x0f, tag)

async def wait_next_aux(dut, tag, limit=12000):
    seen_processing = False
    for _ in range(limit):
        await edge(dut, tag)
        b = busy(dut)
        if b:
            seen_processing = True
        elif seen_processing:
            return
    raise AssertionError(f"{tag}: timeout waiting for next auxiliary input")

async def wait_done(dut, tag, limit=120000):
    seen_processing = False
    stable = None
    for _ in range(limit):
        await edge(dut, tag)
        b = busy(dut)
        if b:
            seen_processing = True
            stable = None
            continue
        if seen_processing:
            v = int(dut.ref_uo_out.value) & 0x3
            if stable == v:
                return v
            stable = v
    raise AssertionError(f"{tag}: timeout waiting for DONE")

def make_case(param, seed, tamper_index=None):
    p = PARAMS[param]
    rng = random.Random(seed)
    regenerated = [rng.randrange(Q) for _ in range(p["n_tot"])]

    enc = []
    for i, x in enumerate(regenerated):
        d = p["du"] if i < p["split"] else p["dv"]
        enc.append(compress(x, d))

    if tamper_index is not None:
        d = p["du"] if tamper_index < p["split"] else p["dv"]
        enc[tamper_index] ^= 1
        enc[tamper_index] &= (1 << d) - 1

    c1 = pack_coeffs(enc[:p["split"]], p["du"])
    c2 = pack_coeffs(enc[p["split"]:], p["dv"])
    return c1 + c2, regenerated

async def run_pass2(dut, param, seed, tamper_index=None):
    p = PARAMS[param]
    tag = f"{p['name']} seed={seed} tamper={tamper_index}"
    ciphertext, regenerated = make_case(param, seed, tamper_index)

    await pulse_start(dut, param, phase=1, tag=tag)

    host_acc = 0
    host_bits = 0
    coeff_idx = 0

    for byte in ciphertext:
        while coeff_idx < p["n_tot"]:
            d = p["du"] if coeff_idx < p["split"] else p["dv"]
            if host_bits < d:
                break
            host_acc >>= d
            host_bits -= d
            await send_aux(dut, regenerated[coeff_idx], tag)
            coeff_idx += 1
            await wait_next_aux(dut, tag)

        await wait_ready(dut, tag)
        await pulse_wr(dut, byte, tag)

        host_acc |= byte << host_bits
        host_bits += 8

        while coeff_idx < p["n_tot"]:
            d = p["du"] if coeff_idx < p["split"] else p["dv"]
            if host_bits < d:
                break
            host_acc >>= d
            host_bits -= d
            await send_aux(dut, regenerated[coeff_idx], tag)
            coeff_idx += 1
            if coeff_idx < p["n_tot"]:
                await wait_next_aux(dut, tag)

    assert coeff_idx == p["n_tot"]
    assert host_bits == 0

    result = await wait_done(dut, tag)
    ref_result = int(dut.ref_uo_out.value) & 0x3
    opt_result = int(dut.opt_uo_out.value) & 0x3
    assert ref_result == opt_result == result

    expected_match = tamper_index is None
    match = bool(result & 1)
    fault = bool(result & 2)

    assert match == expected_match, (
        f"{tag}: reference itself unexpected MATCH={match}, "
        f"expected={expected_match}"
    )
    assert not fault, f"{tag}: reference/optimized FAULT asserted"

@cocotb.test()
async def test_opt1_equivalence(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    set_uio(dut)
    dut.rst_n.value = 0
    await Timer(50, unit="ns")
    dut.rst_n.value = 1
    await edge(dut, "reset")

    # Full pass-2 clean + tamper coverage for all three parameter sets.
    await run_pass2(dut, 0, 0x512A)
    dut.rst_n.value = 0
    await edge(dut, "reset-between")
    dut.rst_n.value = 1
    await edge(dut, "reset-between-release")

    await run_pass2(dut, 0, 0x512A, tamper_index=767)
    dut.rst_n.value = 0
    await edge(dut, "reset-between")
    dut.rst_n.value = 1
    await edge(dut, "reset-between-release")

    await run_pass2(dut, 1, 0x768A)
    dut.rst_n.value = 0
    await edge(dut, "reset-between")
    dut.rst_n.value = 1
    await edge(dut, "reset-between-release")

    await run_pass2(dut, 2, 0x1024A)
    dut.rst_n.value = 0
    await edge(dut, "reset-final")
    dut.rst_n.value = 1
    await edge(dut, "reset-final-release")

    # Extra short randomized reset/start sequences to exercise the sticky
    # mismatch reset behavior.
    for i in range(20):
        await pulse_start(dut, i % 3, phase=i & 1, tag=f"start-only-{i}")
        dut.rst_n.value = 0
        await edge(dut, f"short-reset-{i}")
        dut.rst_n.value = 1
        await edge(dut, f"short-release-{i}")

    cocotb.log.info("OPT1 equivalence PASS")
