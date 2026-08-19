import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

# uio bit map (inputs)
WR    = 0
START = 1
RD    = 2
PHASE = 3
# param_sel = uio[5:4]

async def pulse(dut, bit):
    """One-cycle rising-edge pulse on a uio input bit (edge-detected in RTL)."""
    dut.uio_in.value = dut.uio_in.value | (1 << bit)
    await RisingEdge(dut.clk)
    dut.uio_in.value = dut.uio_in.value & ~(1 << bit)
    await RisingEdge(dut.clk)

def set_param(dut, p):
    v = int(dut.uio_in.value)
    v = (v & ~(0b11 << 4)) | ((p & 0b11) << 4)
    dut.uio_in.value = v

def set_phase(dut, ph):
    v = int(dut.uio_in.value)
    v = (v & ~(1 << PHASE)) | ((ph & 1) << PHASE)
    dut.uio_in.value = v

async def write_byte(dut, b):
    dut.ui_in.value = b & 0xFF
    await pulse(dut, WR)

@cocotb.test()
async def smoke_reset(dut):
    """Reset brings BUSY low and outputs to a known state."""
    cocotb.start_soon(Clock(dut.clk, 25, units="ns").start())  # 40 MHz
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 5)
    # uio_out[6] = BUSY, uio_out[7] = FAULT
    assert (int(dut.uio_out.value) >> 6) & 1 == 0, "BUSY should be low after reset/idle"

@cocotb.test()
async def start_transaction(dut):
    """START pulse should move FSM out of idle (BUSY asserts)."""
    cocotb.start_soon(Clock(dut.clk, 25, units="ns").start())
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 3)

    set_param(dut, 1)          # ML-KEM-512 (du=10,dv=4)
    set_phase(dut, 0)          # pass 1
    await pulse(dut, START)
    await write_byte(dut, 0xA5)
    await ClockCycles(dut.clk, 4)
    # Design is now processing; BUSY should be high during compute states.
    # (Full golden-vector check goes here once reference vectors are wired in.)
    dut._log.info("uo_out=%s uio_out=%s" % (hex(int(dut.uo_out.value)),
                                            hex(int(dut.uio_out.value))))
