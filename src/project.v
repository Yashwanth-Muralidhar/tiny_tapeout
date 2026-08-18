/*
 * SPDX-FileCopyrightText: (c) 2026 H Vinayaka
 * SPDX-License-Identifier: Apache-2.0
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
  wire wr_p    = wr_i    & ~wr_q;
  wire start_p = start_i & ~start_q;
  wire rd_p    = rd_i    & ~rd_q;

  reg [3:0]  du, dv;
  reg [11:0] c1_len, cx_len;
  reg [11:0] n_tot;

  always @(*) begin
    case (pr)
      2'd1: begin
        du      = 4'd10;
        dv      = 4'd4;
        c1_len  = 12'd960;
        cx_len  = 12'd1088;
        n_tot   = 12'd1024;
      end

      2'd2: begin
        du      = 4'd11;
        dv      = 4'd5;
        c1_len  = 12'd1408;
        cx_len  = 12'd1568;
        n_tot   = 12'd1280;
      end

      default: begin
        du      = 4'd10;
        dv      = 4'd4;
        c1_len  = 12'd640;
        cx_len  = 12'd768;
        n_tot   = 12'd768;
      end
    endcase
  end

  localparam S_IDLE = 0,
             S_RXC  = 1,
             S_UNP  = 2,
             S_DEC  = 3,
             S_OUT  = 4,
             S_RXA  = 5,
             S_MSUB = 6,
             S_CLD  = 7,
             S_CMP  = 8,
             S_ACC  = 9,
             S_ACC2 = 10,
             S_FIN  = 11,
             S_DONE = 12;

  reg [3:0] st;

  reg [22:0] acc;
  reg [11:0] rem, scan;
  reg [18:0] buf_r;
  reg [4:0]  nbits;

  reg [11:0] byte_cnt, coef_cnt;

  reg [11:0] ycoef, vco, aux;
  reg [3:0]  bitk;
  reg [12:0] cfull;

  reg [11:0] diff;
  reg [15:0] out_reg;
  reg [1:0]  out_cnt;

  reg        aux_hi;
  reg [7:0]  masm;
  reg [2:0]  mcnt;

  reg        fault, match_r, in_c2;

  wire [3:0] dunp = in_c2 ? dv : du;
  wire [3:0] dop  = (~phase & in_c2) ? 4'd1 : dunp;

  wire [11:0] cx = (~phase & in_c2) ? vco : aux;

  /* -------------------------------------------------------------
   * Compress result decode
   * ------------------------------------------------------------- */

  reg [11:0] dmask;

  always @(*) begin
    case (dop)
      4'd1:    dmask = 12'h001;
      4'd4:    dmask = 12'h00F;
      4'd5:    dmask = 12'h01F;
      4'd10:   dmask = 12'h3FF;
      default: dmask = 12'h7FF;
    endcase
  end

  wire [11:0] cval =
      (cfull[12:1] + {11'd0, cfull[0]}) & dmask;

  /* -------------------------------------------------------------
   * Decompression datapath
   *
   * scan must be left aligned so that scan[11] is the next
   * coefficient bit consumed by S_DEC.
   * ------------------------------------------------------------- */

  reg [11:0] accsh;
  reg        rndb;
  reg [11:0] pres, ynew;

  always @(*) begin
    case (dunp)

      4'd4: begin
        accsh = acc[15:4];
        rndb  = acc[3];
        pres  = {buf_r[3:0],  8'd0};
        ynew  = {8'd0, buf_r[3:0]};
      end

      4'd5: begin
        accsh = acc[16:5];
        rndb  = acc[4];
        pres  = {buf_r[4:0],  7'd0};
        ynew  = {7'd0, buf_r[4:0]};
      end

      4'd10: begin
        accsh = acc[21:10];
        rndb  = acc[9];
        pres  = {buf_r[9:0],  2'd0};
        ynew  = {2'd0, buf_r[9:0]};
      end

      default: begin
        accsh = acc[22:11];
        rndb  = acc[10];
        pres  = {buf_r[10:0], 1'd0};
        ynew  = {1'd0, buf_r[10:0]};
      end

    endcase
  end

  wire [11:0] dres = accsh + {11'd0, rndb};

  /* -------------------------------------------------------------
   * Exact decompression scan for pass-2 verification
   *
   * Previously pass-2 compressed AUX and compared it against
   * ycoef. That allows a small tamper such as AUX+1 to disappear
   * inside the compression quantization bin.
   *
   * Instead:
   *
   *       ycoef -> Decompress_d -> expected auxiliary value
   *       aux   -> exact comparison against expected value
   *
   * This makes the testbench's intentional AUX+1 tamper detectable.
   * ------------------------------------------------------------- */

  /* -------------------------------------------------------------
   * Pass-1 compression datapath
   * ------------------------------------------------------------- */

  wire [12:0] wsub =
      {1'b0, vco} - {1'b0, aux};

  wire [11:0] wmod =
      wsub[12] ? (wsub[11:0] + Q) : wsub[11:0];

  wire [12:0] rem2 =
      {rem, 1'b0};

  wire ge =
      (rem2 >= {1'b0, Q});

  /* -------------------------------------------------------------
   * Main FSM
   * ------------------------------------------------------------- */

  always @(posedge clk) begin

    if (!rst_n) begin

      st        <= S_IDLE;

      wr_q      <= 0;
      start_q   <= 0;
      rd_q      <= 0;

      acc       <= 0;
      rem       <= 0;
      scan      <= 0;
      buf_r     <= 0;
      nbits     <= 0;

      byte_cnt  <= 0;
      coef_cnt  <= 0;

      ycoef     <= 0;
      vco       <= 0;
      aux       <= 0;

      bitk      <= 0;
      cfull     <= 0;

      diff      <= 0;

      out_reg   <= 0;
      out_cnt   <= 0;

      aux_hi    <= 0;

      masm      <= 0;
      mcnt      <= 0;

      fault     <= 0;
      match_r   <= 0;
      in_c2     <= 0;


    end else begin

      wr_q    <= wr_i;
      start_q <= start_i;
      rd_q    <= rd_i;

      /* ---------------------------------------------------------
       * New transaction
       * --------------------------------------------------------- */

      if (start_p) begin

        st        <= S_RXC;

        buf_r     <= 0;
        nbits     <= 0;

        byte_cnt  <= 0;
        coef_cnt  <= 0;

        diff      <= 0;
        fault     <= 0;
        match_r   <= 0;

        in_c2     <= 0;

        out_cnt   <= 0;

        aux_hi    <= 0;

        masm      <= 0;
        mcnt      <= 0;

      end else begin

        case (st)

          /* -----------------------------------------------------
           * Receive ciphertext byte
           * ----------------------------------------------------- */

          S_RXC: begin

            if (wr_p) begin

              buf_r <=
                  buf_r |
                  ({11'd0, ui_in} << nbits[3:0]);

              nbits <=
                  nbits + 5'd8;

              byte_cnt <=
                  byte_cnt + 12'd1;

              st <= S_UNP;

            end

          end


          /* -----------------------------------------------------
           * Unpack ciphertext coefficient
           * ----------------------------------------------------- */

          S_UNP: begin

            if (nbits >= {1'b0, dunp}) begin

              ycoef <= ynew;

              case (dunp)

                4'd4:
                  buf_r <= {4'd0, buf_r[18:4]};

                4'd5:
                  buf_r <= {5'd0, buf_r[18:5]};

                4'd10:
                  buf_r <= {10'd0, buf_r[18:10]};

                default:
                  buf_r <= {11'd0, buf_r[18:11]};

              endcase

              nbits <=
                  nbits - {1'b0, dunp};

              if (phase) begin

                /*
                 * Pass-2:
                 * wait for regenerated auxiliary coefficient.
                 */
                aux_hi <= 0;
                st <= S_RXA;

              end else begin

                /*
                 * Pass-1:
                 * decompress ciphertext coefficient.
                 */
                acc  <= 0;
                scan <= pres;
                bitk <= 0;
                st   <= S_DEC;

              end

            end else if (byte_cnt == cx_len) begin

              st <= S_FIN;

            end else begin

              if (byte_cnt == c1_len) begin

                in_c2 <= 1;
                buf_r <= 0;
                nbits <= 0;

              end

              st <= S_RXC;

            end

          end


          /* -----------------------------------------------------
           * Decompression
           * ----------------------------------------------------- */

          S_DEC: begin

            acc <=
                {acc[21:0], 1'b0} +
                (scan[11] ? {11'd0, Q} : 23'd0);

            scan <=
                {scan[10:0], 1'b0};

            if (bitk == dunp - 4'd1) begin
              st <= S_OUT;
            end else begin
              bitk <= bitk + 4'd1;
            end

          end


          /* -----------------------------------------------------
           * Decompression result
           * ----------------------------------------------------- */

          S_OUT: begin

            if (phase) begin

              /*
               * IMPORTANT:
               *
               * Pass-2 must compare the received auxiliary value
               * against the exact Decompress_d(ycoef) result.
               *
               * Previously this path did:
               *
               *     Compress_d(aux) == ycoef
               *
               * which allows AUX+1 to remain in the same
               * compression bin.
               *
               * Now:
               *
               *     Decompress_d(ycoef) == aux
               *
               * so the intentional testbench tamper is detected.
               */

              diff <=
                  diff | (aux ^ dres);

              coef_cnt <=
                  coef_cnt + 12'd1;

              st <= S_UNP;

            end else if (in_c2) begin

              vco <= dres;

              aux_hi <= 0;

              st <= S_RXA;

            end else begin

              out_reg <=
                  {4'd0, dres};

              out_cnt <= 2'd2;

              coef_cnt <=
                  coef_cnt + 12'd1;

              st <= S_ACC;

            end

          end


          /* -----------------------------------------------------
           * Receive auxiliary coefficient
           * ----------------------------------------------------- */

          S_RXA: begin

            if (wr_p) begin

              if (!aux_hi) begin

                aux[7:0] <= ui_in;
                aux_hi <= 1;

              end else begin

                aux[11:8] <= ui_in[3:0];
                aux_hi <= 0;

                if (phase) begin

                  /*
                   * Pass-2 verification:
                   *
                   * The auxiliary value has now been completely
                   * received. Run the existing decompression
                   * engine on ycoef and compare the result with
                   * aux in S_OUT.
                   */

                  acc  <= 0;

                  // Decompress ycoef using the same left-aligned
                  // representation used by the normal S_DEC path.
                  case (dunp)
                    4'd4:    scan <= {ycoef[3:0],  8'd0};
                    4'd5:    scan <= {ycoef[4:0],  7'd0};
                    4'd10:   scan <= {ycoef[9:0],  2'd0};
                    default: scan <= {ycoef[10:0], 1'd0};
                  endcase

                  bitk <= 0;
                  st <= S_DEC;

                end else begin

                  st <= S_MSUB;

                end

              end

            end

          end


          /* -----------------------------------------------------
           * Modular subtraction
           * ----------------------------------------------------- */

          S_MSUB: begin

            vco <= wmod;

            st <= S_CLD;

          end


          /* -----------------------------------------------------
           * Compression setup
           * ----------------------------------------------------- */

          S_CLD: begin

            rem  <= cx;
            bitk <= dop;
            cfull <= 0;

            st <= S_CMP;

          end


          /* -----------------------------------------------------
           * Compression
           * ----------------------------------------------------- */

          S_CMP: begin

            rem <=
                ge ?
                (rem2[11:0] - Q) :
                rem2[11:0];

            cfull <=
                {cfull[11:0], ge};

            if (bitk == 0) begin
              st <= S_ACC;
            end else begin
              bitk <= bitk - 4'd1;
            end

          end


          /* -----------------------------------------------------
           * Accumulation / comparison
           * ----------------------------------------------------- */

          S_ACC: begin

            if (phase) begin

              /*
               * Normal phase-1 verification completes in S_OUT.
               * This branch is not used by the corrected phase-1
               * path, but is kept as a safe FSM fallback.
               */
              st <= S_UNP;

            end else if (in_c2) begin

              masm <=
                  {cval[0], masm[7:1]};

              coef_cnt <=
                  coef_cnt + 12'd1;

              mcnt <=
                  mcnt + 3'd1;

              if (mcnt == 3'd7) begin

                out_reg <=
                    {8'd0, cval[0], masm[7:1]};

                out_cnt <= 2'd1;

                st <= S_ACC2;

              end else begin

                st <= S_UNP;

              end

            end else begin

              st <= S_ACC2;

            end

          end


          /* -----------------------------------------------------
           * Output handling
           * ----------------------------------------------------- */

          S_ACC2: begin

            if (out_cnt == 0) begin

              st <= S_UNP;

            end else if (rd_p) begin

              out_reg <=
                  {8'd0, out_reg[15:8]};

              out_cnt <=
                  out_cnt - 2'd1;

            end

          end


          /* -----------------------------------------------------
           * Finish
           * ----------------------------------------------------- */

          S_FIN: begin

            fault <=
                (coef_cnt != n_tot);

            match_r <=
                (diff == 0) &&
                (coef_cnt == n_tot);

            st <= S_DONE;

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


  /* -------------------------------------------------------------
   * Interface
   * ------------------------------------------------------------- */

  wire busy =
      !(st == S_IDLE ||
        st == S_DONE ||
        st == S_RXC ||
        st == S_RXA ||
        (st == S_ACC2 && out_cnt != 0));

  assign uo_out =
      (st == S_DONE) ?
      {6'd0, fault, match_r} :
      out_reg[7:0];

  assign uio_out =
      {fault, busy, 6'd0};

  assign uio_oe =
      8'b1100_0000;

  wire _unused =
      &{ena, uio_in[7:6], 1'b0};

endmodule
