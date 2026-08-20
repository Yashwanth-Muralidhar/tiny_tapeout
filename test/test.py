async def run_pass1(dut, param, seed):
    """Exercise the compression path (encapsulation side): feed random
    plaintext-domain coefficients through decompress-then-recompress,
    read back masm/coefficient bytes, cross-check against the golden
    model's Compress/Decompress functions.

    For the c2/in_c2 region the DUT detours through S_RXA to request
    the plaintext coefficient (same role `aux` plays in run_pass2's
    mismatch check) before it can finish the recompression -> masm
    path in S_MSUB/S_CLD/S_CMP. That aux value must be supplied here;
    the DUT is correctly waiting, not stuck.
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

    # Index of the next c2-region coefficient whose plaintext value the
    # DUT will request via S_RXA. Only coefficients >= split (the dv/c2
    # region) ever hit S_RXA in phase=0.
    aux_idx = p["split"]

    async def drain(byte_idx):
        """Service S_RXA (feed aux) and S_ACC2 (drain pending output)
        until the DUT is ready for the next ciphertext byte."""
        nonlocal aux_idx
        while True:
            st = int(dut.user_project.st.value)
            if st == 5:  # S_RXA
                assert aux_idx < p["n_tot"], (
                    f"{p['name']} pass1: unexpected S_RXA before c2 region "
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
        await drain(byte)
        await pulse_wr(dut, byte)

    # Drain any trailing S_RXA request / pending output after the last byte.
    await drain(len(ciphertext))

    result = await wait_done(dut)
    assert aux_idx == p["n_tot"], (
        f"{p['name']} pass1: aux count mismatch ({aux_idx} != {p['n_tot']})"
    )
    # pass-1 clean run should not raise FAULT (coef_cnt should reach n_tot)
    assert not (result & 2), f"{p['name']} pass1: unexpected FAULT"
