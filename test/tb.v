`timescale 1ns / 1ps

module tb (
    input clk,
    input rst_n
);

    // Internal signals
    reg          clk_int;
    reg          rst_n_int;
    reg  [7:0]   din;
    reg          din_valid;
    wire [7:0]   dout;
    wire         dout_valid;
    
    // ML-KEM top module
    ml_kem_decap dut (
        .clk(clk_int),
        .rst_n(rst_n_int),
        .din(din),
        .din_valid(din_valid),
        .dout(dout),
        .dout_valid(dout_valid)
    );
    
    // Cocotb will override clk and rst_n
    initial begin
        clk_int = 0;
        rst_n_int = 0;
    end
    
    always @(*) begin
        clk_int = clk;
        rst_n_int = rst_n;
    end
    
endmodule
