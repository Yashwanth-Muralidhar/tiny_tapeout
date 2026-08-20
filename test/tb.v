`timescale 1ns / 1ps
`default_nettype none

module tb;
    reg clk, rst_n, ena;
    reg [7:0] ui_in, uio_in;
    wire [7:0] uo_out, uio_out, uio_oe;

`ifdef GL_TEST
    wire VPWR = 1'b1;
    wire VGND = 1'b0;
`endif

    // Dump waves for local debugging
    initial begin
        $dumpfile("tb.vcd");
        $dumpvars(0, tb);
    end

    tt_um_vinayaka_pqc_fo user_project (
`ifdef GL_TEST
        .VPWR(VPWR),
        .VGND(VGND),
`endif
        .ui_in  (ui_in),
        .uo_out (uo_out),
        .uio_in (uio_in),
        .uio_out(uio_out),
        .uio_oe (uio_oe),
        .ena    (ena),
        .clk    (clk),
        .rst_n  (rst_n)
    );

endmodule
