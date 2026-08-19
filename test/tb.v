`timescale 1ns/1ps
`default_nettype none

`include "../src/project_opt1_isolated_renamed.v"

module tb;

    reg  [7:0] ui_in;
    wire [7:0] ref_uo_out;
    wire [7:0] ref_uio_out;
    wire [7:0] ref_uio_oe;

    wire [7:0] opt_uo_out;
    wire [7:0] opt_uio_out;
    wire [7:0] opt_uio_oe;

    reg  [7:0] uio_in;
    reg        ena;
    reg        clk;
    reg        rst_n;

    tt_um_vinayaka_pqc_fo ref (
        .ui_in   (ui_in),
        .uo_out  (ref_uo_out),
        .uio_in  (uio_in),
        .uio_out (ref_uio_out),
        .uio_oe  (ref_uio_oe),
        .ena      (ena),
        .clk      (clk),
        .rst_n    (rst_n)
    );

    tt_um_vinayaka_pqc_fo_opt opt (
        .ui_in   (ui_in),
        .uo_out  (opt_uo_out),
        .uio_in  (uio_in),
        .uio_out (opt_uio_out),
        .uio_oe  (opt_uio_oe),
        .ena      (ena),
        .clk      (clk),
        .rst_n    (rst_n)
    );

endmodule

`default_nettype wire
