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
    dut.uio_in.value = (((param & 3) << 4) | ((phase & 1) << 3) |
                         ((rd & 1) << 2) | ((start & 1) << 1) | (wr & 1))

def busy(dut):
    return (int(dut.uio_out.value) >> 6) & 1

STATE_NAMES = ["IDLE","RXC","UNP","DEC","OUT","RXA","MSUB","CLD","CMP","ACC","ACC2","FIN","DONE"]

def stname(dut):
    try:
        v = int(dut.user_project.st.value)
        return STATE_NAMES[v] if v < len(STATE_NAMES) else str(v)
    except Exception as e:
        return f"?({e})"

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

async def pulse_rd(dut):
    set_uio(dut, rd=1)
    await RisingEdge(dut.clk)
    set_uio(dut)
    await RisingEdge(dut.clk)

async def wait_ready(dut, limit=3000):
    for _ in range(limit):
        if not busy(dut):
            return
        await RisingEdge(dut.clk)
    raise AssertionError(f"Timeout waiting for ready, stuck in st={stname(dut)}")

async def wait_rxa(dut, limit=3000):
    for _ in range(limit):
        if int(dut.user_project.st.value) == 5:
            return
        await RisingEdge(dut.clk)
    raise AssertionError(f"Timeout waiting for S_RXA, stuck in st={stname(dut)}")

async def send_aux(dut, coeff):
    assert 0 <= coeff < Q
    await wait_rxa(dut)
    await pulse_wr(dut, coeff & 0xFF)
    await pulse_wr(dut, (coeff >> 8) & 0x0F)

async def wait_done(dut, limit=200000):
    # The caller may arrive here after drain() has already observed busy=0.
    # In that case the DUT can already be in S_DONE, so do not require a
    # second busy assertion before accepting the result.
    if int(dut.user_project.st.value) == 12:
        return int(dut.uo_out.value) & 0x3

    seen_processing = busy(dut)
    stable = None
    last_st = None
    last_busy = None
    last_uo = None
    cycles = 0

    for _ in range(limit):
        await RisingEdge(dut.clk)
        cycles += 1

        b = busy(dut)
        st = int(dut.user_project.st.value)
        uo = int(dut.uo_out.value) & 0xFF

        last_st = st
        last_busy = b
        last_uo = uo

        # DONE is the authoritative completion state.
        if st == 12:
            return uo & 0x3

        if b:
            seen_processing = True
            stable = None
            continue

        if seen_processing:
            v = uo & 0x3
            if stable == v:
                return v
            stable = v

    raise AssertionError(
        f"Timeout waiting for DONE after {cycles} cycles: "
        f"st={last_st} ({stname(dut)}), busy={last_busy}, "
        f"uo_out=0x{last_uo:02x}"
    )

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
    ciphertext, regenerated = make_case(param, seed, tamper_index)
    await pulse_start(dut, param, phase=1)

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
            await send_aux(dut, regenerated[coeff_idx])
            coeff_idx += 1

        await wait_ready(dut)
        await pulse_wr(dut, byte)
        host_acc |= byte << host_bits
        host_bits += 8

        while coeff_idx < p["n_tot"]:
            d = p["du"] if coeff_idx < p["split"] else p["dv"]
            if host_bits < d:
                break
            host_acc >>= d
            host_bits -= d
            await send_aux(dut, regenerated[coeff_idx])
            coeff_idx += 1

    assert coeff_idx == p["n_tot"]
    result = await wait_done(dut)
    match = bool(result & 1)
    fault = bool(result & 2)
    expected = tamper_index is None
    assert match == expected, f"{p['name']}: expected MATCH={expected}, got {result:02b}"
    assert not fault, f"{p['name']}: unexpected FAULT"

async def run_pass1(dut, param, seed):
    """Phase-0 test matching the current RTL FSM.

    Phase 0 enters S_RXA only for the c2 region. Therefore aux starts at
    split and exactly n_tot-split auxiliary coefficients are supplied.
    """
    p = PARAMS[param]
    rng = random.Random(seed)
    coeffs = [rng.randrange(Q) for _ in range(p["n_tot"])]

    enc = []
    for i, x in enumerate(coeffs):
        d = p["du"] if i < p["split"] else p["dv"]
        enc.append(compress(x, d))

    c1 = pack_coeffs(enc[:p["split"]], p["du"])
    c2 = pack_coeffs(enc[p["split"]:], p["dv"])
    ciphertext = c1 + c2

    await pulse_start(dut, param, phase=0)

    # c1: S_UNP -> S_DEC -> S_OUT -> S_ACC
    # c2: S_UNP -> S_DEC -> S_OUT -> S_RXA
    aux_idx = p["split"]

    async def drain():
        nonlocal aux_idx
        while True:
            st = int(dut.user_project.st.value)

            if st == 5:  # S_RXA
                assert aux_idx < p["n_tot"], (
                    f"{p['name']} pass1: unexpected S_RXA "
                    f"(aux_idx={aux_idx})"
                )
                await send_aux(dut, coeffs[aux_idx])
                aux_idx += 1
                continue

            if not busy(dut):
                if st == 10:  # S_ACC2, output pending
                    await pulse_rd(dut)
                    continue
                return

            await RisingEdge(dut.clk)

    for byte in ciphertext:
        await drain()
        await pulse_wr(dut, byte)

    await drain()

    # At this point all ciphertext bytes have been sent and all observed
    # S_RXA requests have been serviced.  Keep the final FSM state visible
    # if completion fails.
    result = await wait_done(dut)
    expected_aux = p["n_tot"] - p["split"]

    assert aux_idx == p["n_tot"], (
        f"{p['name']} pass1: aux count mismatch "
        f"({aux_idx - p['split']} != {expected_aux})"
    )
    assert not (result & 2), f"{p['name']} pass1: unexpected FAULT"

@cocotb.test()
async def test_v8_mlkem512_clean_and_tamper(dut):
    await start_clock(dut)
    await run_pass2(dut, 0, 0x512A)
    await reset_dut(dut)
    await run_pass2(dut, 0, 0x512A, tamper_index=767)

@cocotb.test()
async def test_v8_mlkem768_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 1, 0x768A)

@cocotb.test()
async def test_v8_mlkem1024_clean(dut):
    await start_clock(dut)
    await run_pass2(dut, 2, 0x1024A)

@cocotb.test()
async def test_v8_mlkem512_tamper_each_boundary(dut):
    await start_clock(dut)
    for idx in (0, 1, 511, 512, 513, 767):
        await run_pass2(dut, 0, 0x9999 + idx, tamper_index=idx)
        await reset_dut(dut)

@cocotb.test()
async def test_v8_pass1_all_params(dut):
    await start_clock(dut)
    for param in (0, 1, 2):
        await run_pass1(dut, param, 0xF00D + param)
        await reset_dut(dut)
