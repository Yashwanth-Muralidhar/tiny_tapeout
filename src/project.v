/*
 * SPDX-FileCopyrightText: (c) 2026 H Vinayaka
 * SPDX-License-Identifier: Apache-2.0
 *
 * ============================================================
 *  UNVERIFIED - ALL SIX OPTIMIZATIONS + CLEANUPS + OPT7.
 *  MUST be equivalence-checked (yosys miter) vs golden baseline
 *  AND pass cocotb golden vectors + AUX+1 tamper before use.
 *  OPT5/OPT6 are structural and direction-sensitive.
 *  Revert any single change via its // OPT#n markers.
 *
 *  OPT1 : diff[11:0] -> 1-bit sticky diff_s
 *  OPT3 : out_reg[15:0] -> [11:0]
 *  OPT4a: byte_cnt/coef_cnt -> 11 bits
 *  OPT4b: register c1/cx/n limits once (remove live param mux)
 *  OPT5 : constant-shift unpacker (top-loaded buf_r)
 *  OPT6 : left-aligned acc, fixed 11 S_DEC iters (no tap muxes)
 *  OPT7 : cval datapath -> single XOR (cfull[1]^cfull[0])
 *  FIX-A: bitk compare width; FIX-B: 11-bit decode regs
 * ============================================================
 */

`default_nettype none

module tt_um_vinayaka_pqc_fo (
  input  wire [7:0] ui_in,
  output wire [7:0] uo_out,
  input  wire [7:0] uio_in,
  output wire [7:0] uio_out,
  output wire [7:0] uio_oe,
  input  wire       ena,
  input  wire       clk,
  input  wire       rst_n
);
 
localparam [11:0] Q = 12'd3329;

wire wr_i    = uio_in[0];
wire start_i = uio_in[1];
wire rd_i    = uio_in[2];
wire phase   = uio_in[3];
wire [1:0] pr = uio_in[5:4];

reg wr_q, start_q, rd_q;
wire wr_p    = wr_i & ~wr_q;
wire start_p = start_i & ~start_q;
wire rd_p    = rd_i & ~rd_q;

// OPT4b + FIX-B: decode used only to load registered limits at start.
reg [3:0]  du, dv;
reg [10:0] dc1_len, dcx_len, dn_tot;

always @(*) begin
  case (pr)
    2'd1: begin
      du = 4'd10; dv = 4'd4;
      dc1_len = 11'd960;  dcx_len = 11'd1088; dn_tot = 11'd1024;
    end
    2'd2: begin
      du = 4'd11; dv = 4'd5;
      dc1_len = 11'd1408; dcx_len = 11'd1568; dn_tot = 11'd1280;
    end
    default: begin
      du = 4'd10; dv = 4'd4;
      dc1_len = 11'd640;  dcx_len = 11'd768;  dn_tot = 11'd768;
    end
  endcase
end

localparam S_IDLE  = 0, S_RXC = 1, S_UNP = 2, S_DEC = 3, S_OUT = 4,
           S_RXA   = 5, S_MSUB = 6, S_CLD = 7, S_CMP = 8, S_ACC = 9,
           S_ACC2  = 10, S_FIN = 11, S_DONE = 12;

reg [3:0] st;

reg [22:0] acc;
reg [11:0] rem, scan;
reg [18:0] buf_r;
reg [4:0]  nbits;

reg [10:0] byte_cnt, coef_cnt;        // OPT4a

reg [10:0] lim_c1, lim_cx, lim_n;     // OPT4b

reg [10:0] ycoef;
reg [11:0] vco, aux;
reg [3:0]  bitk;
reg [12:0] cfull;

reg        diff_s;                    // OPT1
reg [11:0] out_reg;                   // OPT3
reg [1:0]  out_cnt;

reg        aux_hi;
reg [7:0]  masm;
reg [2:0]  mcnt;

reg fault, match_r, in_c2;

wire [3:0] dunp = in_c2 ? dv : du;
wire [3:0] dop  = (~phase & in_c2) ? 4'd1 : dunp;
wire [11:0] cx  = (~phase & in_c2) ? vco : aux;

/* ---------- OPT7: compressed LSB only ----------
 * cval[0] is the only bit ever consumed. With every dmask having
 * bit0=1, cval[0] = LSB of (cfull[12:1] + cfull[0]) = cfull[1]^cfull[0].
 * The 12-bit dmask mux + adder + AND are removed.
 */
wire cval0 = cfull[1] ^ cfull[0];

/* ---------- OPT5: top-of-buffer extract ---------- */
reg [11:0] ynew;
always @(*) begin
  case (dunp)
    4'd4:    ynew = {8'd0, buf_r[18:15]};
    4'd5:    ynew = {7'd0, buf_r[18:14]};
    4'd10:   ynew = {2'd0, buf_r[18:9]};
    default: ynew = {1'd0, buf_r[18:8]};
  endcase
end

/* ---------- OPT6: fixed-tap decompress result ---------- */
wire [11:0] dres  = acc[22:11] + {11'd0, acc[10]};

/* ---------- pass-1 compression datapath ---------- */
wire [12:0] wsub = {1'b0, vco} - {1'b0, aux};
wire [11:0] wmod = wsub[12] ? (wsub[11:0] + Q) : wsub[11:0];
wire [12:0] rem2 = {rem, 1'b0};
wire ge = (rem2 >= {1'b0, Q});

/* ---------- OPT5/OPT6 left-align helper ---------- */
function [11:0] leftalign;
  input [11:0] v;
  input [3:0]  d;
  begin
    leftalign = v << (4'd12 - d);
  end
endfunction

/* ---------- main FSM ---------- */
always @(posedge clk) begin
  if (!rst_n) begin
    st <= S_IDLE;
    wr_q <= 0; start_q <= 0; rd_q <= 0;
    acc <= 0; rem <= 0; scan <= 0; buf_r <= 0; nbits <= 0;
    byte_cnt <= 0; coef_cnt <= 0;
    lim_c1 <= 0; lim_cx <= 0; lim_n <= 0;
    ycoef <= 0; vco <= 0; aux <= 0; bitk <= 0; cfull <= 0;
    diff_s <= 0; out_reg <= 0; out_cnt <= 0;
    aux_hi <= 0; masm <= 0; mcnt <= 0;
    fault <= 0; match_r <= 0; in_c2 <= 0;
  end else begin
    wr_q <= wr_i; start_q <= start_i; rd_q <= rd_i;

    if (start_p) begin
      st <= S_RXC;
      buf_r <= 0; nbits <= 0; byte_cnt <= 0; coef_cnt <= 0;
      diff_s <= 0; fault <= 0; match_r <= 0; in_c2 <= 0;
      out_cnt <= 0; aux_hi <= 0; masm <= 0; mcnt <= 0;
      lim_c1 <= dc1_len;
      lim_cx <= dcx_len;
      lim_n  <= dn_tot;
    end else begin
      case (st)
        S_RXC: begin
          if (wr_p) begin
            buf_r    <= (buf_r >> 8) | ({11'd0, ui_in} << 11);   // OPT5
            nbits    <= nbits + 5'd8;
            byte_cnt <= byte_cnt + 11'd1;                        // OPT4a
            st       <= S_UNP;
          end
        end

        S_UNP: begin
          if (nbits >= {1'b0, dunp}) begin
            ycoef <= ynew[10:0];
            buf_r <= buf_r << dunp;                              // OPT5
            nbits <= nbits - {1'b0, dunp};
            if (phase) begin
              aux_hi <= 0;
              st     <= S_RXA;
            end else begin
              acc  <= 0;
              scan <= leftalign(ynew, dunp);                     // OPT6
              bitk <= 0;
              st   <= S_DEC;
            end
          end else if ({1'b0, byte_cnt} == {1'b0, lim_cx}) begin
            st <= S_FIN;
          end else begin
            if ({1'b0, byte_cnt} == {1'b0, lim_c1}) begin
              in_c2 <= 1;
              buf_r <= 0;
              nbits <= 0;
            end
            st <= S_RXC;
          end
        end

        S_DEC: begin
          acc  <= {acc[21:0], 1'b0} +
                  (scan[11] ? {11'd0, Q} : 23'd0);
          scan <= {scan[10:0], 1'b0};
          if (bitk == 4'd10) begin        // FIX-A
            st <= S_OUT;
          end else begin
            bitk <= bitk + 4'd1;
          end
        end

        S_OUT: begin
          if (phase) begin
            diff_s   <= diff_s | (|(aux ^ dres));   // OPT1
            coef_cnt <= coef_cnt + 11'd1;
            st       <= S_UNP;
          end else if (in_c2) begin
            vco    <= dres;
            aux_hi <= 0;
            st     <= S_RXA;
          end else begin
            out_reg  <= dres;                        // OPT3
            out_cnt  <= 2'd2;
            coef_cnt <= coef_cnt + 11'd1;
            st       <= S_ACC;
          end
        end

        S_RXA: begin
          if (wr_p) begin
            if (!aux_hi) begin
              aux[7:0] <= ui_in;
              aux_hi   <= 1;
            end else begin
              aux[11:8] <= ui_in[3:0];
              aux_hi    <= 0;
              if (phase) begin
                acc  <= 0;
                scan <= leftalign({1'b0, ycoef}, dunp);  // OPT6
                bitk <= 0;
                st   <= S_DEC;
              end else begin
                st <= S_MSUB;
              end
            end
          end
        end

        S_MSUB: begin
          vco <= wmod;
          st <= S_CLD;
        end

        S_CLD: begin
          rem <= cx;
          bitk <= dop;
          cfull <= 0;
          st <= S_CMP;
        end

        S_CMP: begin
          rem   <= ge ? (rem2[11:0] - Q) : rem2[11:0];
          cfull <= {cfull[11:0], ge};
          if (bitk == 0)
            st <= S_ACC;
          else
            bitk <= bitk - 4'd1;
        end

        S_ACC: begin
          if (phase) begin
            st <= S_UNP;
          end else if (in_c2) begin
            masm     <= {cval0, masm[7:1]};          // OPT7
            coef_cnt <= coef_cnt + 11'd1;
            mcnt     <= mcnt + 3'd1;
            if (mcnt == 3'd7) begin
              out_reg <= {4'd0, cval0, masm[7:1]};   // OPT7
              out_cnt <= 2'd1;
              st      <= S_ACC2;
            end else
              st <= S_UNP;
          end else begin
            st <= S_ACC2;
          end
        end

        S_ACC2: begin
          if (out_cnt == 0)
            st <= S_UNP;
          else if (rd_p) begin
            out_reg <= {4'd0, out_reg[11:4]};
            out_cnt <= out_cnt - 2'd1;
          end
        end

        S_FIN: begin
          fault   <= ({1'b0, coef_cnt} != {1'b0, lim_n});
          match_r <= (!diff_s) && ({1'b0, coef_cnt} == {1'b0, lim_n});
          st      <= S_DONE;
        end

        S_DONE: begin
          st <= S_DONE;
        end

        default: begin
          st <= S_IDLE;
        end
      endcase
    end
  end
end

/* ---------- interface ---------- */
wire busy =
    !(st == S_IDLE || st == S_DONE || st == S_RXC || st == S_RXA ||
      (st == S_ACC2 && out_cnt != 0));

assign uo_out = (st == S_DONE) ? {6'd0, fault, match_r} : out_reg[7:0];
assign uio_out = {fault, busy, 6'd0};
assign uio_oe  = 8'b1100_0000;

wire _unused = &{ena, uio_in[7:6], 1'b0};

endmodule
