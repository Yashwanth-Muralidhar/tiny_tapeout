import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

@cocotb.test()
async def test_reset_and_start(dut):
    clk = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clk.start())

    dut.rst_n.value = 0
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0

    await ClockCycles(dut.clk, 5)

    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    # start pulse on uio_in[1]
    dut.uio_in.value = 0b00000010
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 1)

    assert int(dut.uio_oe.value) == 0b11000000
    cocotb.log.info("reset/start interface test PASSED")
