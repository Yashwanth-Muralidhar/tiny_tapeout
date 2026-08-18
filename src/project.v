`default_nettype none

/*
 * Parameter-agile, divider-free FO backend for ML-KEM decapsulation.
 *
 * Architecture-G Optimized v7 (8-bit I/O preserved; six-pin redesign still separate).
 *
 * Functional architecture is intentionally unchanged from the verified
 * Architecture-G reference. Optimizations in this version target both area
 * area, fanout, and physical implementation quality:
 *   1) Force compact binary FSM encoding instead of Yosys one-hot recoding.
 *   2) Replace the 12-bit mismatch accumulator with a 1-bit sticky mismatch.
 *   3) Narrow stream counters from 12 to 11 bits (max values are < 2048).
 *   4) Narrow the compression bit accumulator from 13 to 12 bits.
 *   5) Narrow the output staging register from 16 to 12 bits.
 *   6) Latch phase/parameter controls at transaction start to isolate pad fanout.
 *   7) Initialize datapath registers at START instead of propagating reset into all D inputs.
 *   8) Reduce the unpacker buffer/scan widths to proven minimums.
 *   9) Replace the 13-bit restoring comparator with a 12-bit threshold check.
 *  10) Remove the dedicated vco register; reuse the stable dres result directly.
 *  11) Reduce the unpacker buffer to 16 bits; retain a 5-bit nbits counter so 16-bit occupancy is representable.
 *  12) Reduce ycoef/cval to 11 bits (ML-KEM coefficient range for d<=11).
 *  13) Reuse coef_cnt[2:0] for message-byte assembly, removing mcnt.
 *  14) Derive MATCH/FAULT combinationally in DONE, removing two result flops.
 *  15) Reuse the 11-bit scan register as the compression quotient storage,
 *      using aux_hi as the final rounding-bit latch; removes cfull storage.
 *  16) Replace the 12-bit output staging register with an 8-bit low-byte
 *      register plus direct high-nibble/message-byte selection.
 *
 * No general multiplier, divider, shifted copy of q, or ciphertext memory.
 * Latency remains determined only by the public ML-KEM parameter and stream
 * protocol. The external 8-bit interface is preserved in this baseline so
 * that the existing verification harness can be reused before the separate
 * six-functional-pin redesign.
 */
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

    // ------------------------------------------------------------------------
    // Control pins / edge detection
    // ------------------------------------------------------------------------
    wire       wr_i    = uio_in[0];
    wire       start_i = uio_in[1];
    wire       rd_i    = uio_in[2];
    wire       phase_i = uio_in[3];          // 0 = pass 1, 1 = pass 2
    wire [1:0] pr_i    = uio_in[5:4];        // 00 = 512, 01 = 768, 10 = 1024

    reg wr_q, start_q, rd_q;
    reg phase_r;
    reg [1:0] pr_r;
    wire       phase = phase_r;
    wire [1:0] pr = pr_r;
    wire wr_p    = wr_i    & ~wr_q;
    wire start_p = start_i & ~start_q;
    wire rd_p    = rd_i    & ~rd_q;

    // ------------------------------------------------------------------------
    // Public ML-KEM parameter selection.
    // Maximum byte/count values are below 2048, so 11 bits are sufficient.
    // ------------------------------------------------------------------------
    reg [3:0]  du, dv;
    reg [10:0] c1_len, cx_len;
    reg [10:0] n_tot;

    always @(*) begin
        case (pr)
            2'd1: begin
                du     = 4'd10;
                dv     = 4'd4;
                c1_len = 11'd960;
                cx_len = 11'd1088;
                n_tot  = 11'd1024;
            end
            2'd2: begin
                du     = 4'd11;
                dv     = 4'd5;
                c1_len = 11'd1408;
                cx_len = 11'd1568;
                n_tot  = 11'd1280;
            end
            default: begin
                du     = 4'd10;
                dv     = 4'd4;
                c1_len = 11'd640;
                cx_len = 11'd768;
                n_tot  = 11'd768;
            end
        endcase
    end

    // ------------------------------------------------------------------------
    // FSM
    // ------------------------------------------------------------------------
    // Keep the 4-bit binary state encoding. The previous run showed Yosys
    // recoding this 13-state FSM one-hot, increasing state storage and decode
    // logic. At the 25 ns target, the area reduction is more valuable than
    // the one-hot decode advantage.
    // ------------------------------------------------------------------------
    (* fsm_encoding = "binary" *)
    reg [3:0] st;

    localparam [3:0]
        S_IDLE = 4'd0,
        S_RXC  = 4'd1,
        S_UNP  = 4'd2,
        S_DEC  = 4'd3,
        S_OUT  = 4'd4,
        S_RXA  = 4'd5,
        S_MSUB = 4'd6,
        S_CLD  = 4'd7,
        S_CMP  = 4'd8,
        S_ACC  = 4'd9,
        S_ACC2 = 4'd10,
        S_FIN  = 4'd11,
        S_DONE = 4'd12;

    // ------------------------------------------------------------------------
    // Datapath/state registers
    // ------------------------------------------------------------------------
    reg [22:0] acc;                 // Decompress accumulator
    reg [11:0] rem;                 // Restoring remainder
    reg [10:0] scan;                // 11-bit left-aligned coefficient bits
    reg [15:0] buf_r;               // 16-bit bit-unpacker buffer; max occupancy is 16 bits
    reg [4:0]  nbits;               // 0..16 during byte unpacking
    reg [10:0] byte_cnt, coef_cnt;  // Maximum values < 2048
    reg [10:0] ycoef;                 // d<=11, so 11 bits are sufficient
    reg [11:0] aux;                  // decompressed/regenerated coefficient
    reg [3:0]  bitk;
    reg        mismatch;            // Sticky: at least one coefficient differs
    reg [7:0]  out_low;              // buffered low byte for 12-bit coefficient output
    reg [1:0]  out_cnt;               // 0=none, 1=message byte, 2=coef low, 3=coef high
    reg        aux_hi;
    reg [7:0]  masm;
    reg        in_c2;

    wire [3:0] dunp = in_c2 ? dv : du;
    wire [3:0] dop  = (~phase & in_c2) ? 4'd1 : dunp;

    // ------------------------------------------------------------------------
    // Decompress / unpack combinational decode.
    // ------------------------------------------------------------------------
    reg [11:0] accsh;
    reg        rndb;
    reg [10:0] pres;
    reg [10:0] ynew;

    always @(*) begin
        case (dunp)
            4'd4: begin
                accsh = acc[15:4];
                rndb  = acc[3];
                pres  = {buf_r[3:0], 7'd0};
                ynew  = {7'd0, buf_r[3:0]};
            end
            4'd5: begin
                accsh = acc[16:5];
                rndb  = acc[4];
                pres  = {buf_r[4:0], 6'd0};
                ynew  = {6'd0, buf_r[4:0]};
            end
            4'd10: begin
                accsh = acc[21:10];
                rndb  = acc[9];
                pres  = {buf_r[9:0], 1'd0};
                ynew  = {1'd0, buf_r[9:0]};
            end
            default: begin
                accsh = acc[22:11];
                rndb  = acc[10];
                pres  = buf_r[10:0];
                ynew  = buf_r[10:0];
            end
        endcase
    end

    wire [11:0] dres = accsh + {11'd0, rndb};

    // ------------------------------------------------------------------------
    // 13-bit modular subtract: dres - aux (mod 3329)
    // ------------------------------------------------------------------------
    wire [12:0] wsub = {1'b0, dres} - {1'b0, aux};
    wire [11:0] wmod = wsub[12] ? (wsub[11:0] + Q) : wsub[11:0];

    // ------------------------------------------------------------------------
    // Restoring divide by Q for Compress.
    // Since rem < Q, 2*rem >= Q is equivalent to rem >= ceil(Q/2) = 1665.
    // This keeps the comparator and remainder update at 12 bits.
    // ------------------------------------------------------------------------
    wire [11:0] rem_shift = {rem[10:0], 1'b0};
    wire        ge        = (rem >= 12'd1665);
    wire [11:0] rem_next  = ge ? (rem_shift - Q) : rem_shift;

    // ------------------------------------------------------------------------
    // Sequential core
    // ------------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            // Only transaction-control flops need reset state. All datapath and
            // status registers are initialized at START before they are observed.
            st      <= S_IDLE;
            wr_q    <= 1'b0;
            start_q <= 1'b0;
            rd_q    <= 1'b0;
            phase_r <= 1'b0;
            pr_r    <= 2'd0;
        end else begin
            wr_q    <= wr_i;
            start_q <= start_i;
            rd_q    <= rd_i;

            if (start_p) begin
                phase_r  <= phase_i;
                pr_r     <= pr_i;
                st       <= S_RXC;
                acc      <= 23'd0;
                rem      <= 12'd0;
                scan     <= 11'd0;
                buf_r    <= 16'd0;
                nbits    <= 5'd0;
                byte_cnt <= 11'd0;
                coef_cnt <= 11'd0;
                ycoef    <= 11'd0;
                aux      <= 12'd0;
                bitk     <= 4'd0;
                mismatch <= 1'b0;
                out_low  <= 8'd0;
                out_cnt  <= 2'd0;
                aux_hi   <= 1'b0;
                masm     <= 8'd0;
                in_c2    <= 1'b0;
            end else begin
                case (st)
                    S_IDLE: begin
                        // wait for start_p
                    end

                    // ----------------------------------------------------------------
                    // Receive one ciphertext byte.
                    // nbits is at most 7 before a byte insertion; after insertion it may reach 16, so 5 bits are required.
                    // ----------------------------------------------------------------
                    S_RXC: if (wr_p) begin
                        buf_r    <= buf_r | ({8'd0, ui_in} << nbits);
                        nbits    <= nbits + 5'd8;
                        byte_cnt <= byte_cnt + 11'd1;
                        st       <= S_UNP;
                    end

                    // ----------------------------------------------------------------
                    // Extract every complete coefficient from the unpack buffer.
                    // ----------------------------------------------------------------
                    S_UNP: begin
                        if (nbits >= {1'b0, dunp}) begin
                            ycoef <= ynew;

                            case (dunp)
                                4'd4:    buf_r <= {4'd0,  buf_r[15:4]};
                                4'd5:    buf_r <= {5'd0,  buf_r[15:5]};
                                4'd10:   buf_r <= {10'd0, buf_r[15:10]};
                                default: buf_r <= {11'd0, buf_r[15:11]};
                            endcase

                            nbits <= nbits - {1'b0, dunp};

                            if (phase) begin
                                // Pass 2: fetch regenerated c' coefficient.
                                aux_hi <= 1'b0;
                                st     <= S_RXA;
                            end else begin
                                // Pass 1: decompress this coefficient.
                                acc  <= 23'd0;
                                scan <= pres;
                                bitk <= 4'd0;
                                st   <= S_DEC;
                            end
                        end else if (byte_cnt == cx_len) begin
                            st <= S_FIN;
                        end else begin
                            if (byte_cnt == c1_len) begin
                                in_c2 <= 1'b1;
                                buf_r <= 16'd0;
                                nbits <= 5'd0;
                            end
                            st <= S_RXC;
                        end
                    end

                    // ----------------------------------------------------------------
                    // Decompress: A <- 2A + (bit ? Q : 0)
                    // ----------------------------------------------------------------
                    S_DEC: begin
                        acc  <= {acc[21:0], 1'b0} +
                                (scan[10] ? {11'd0, Q} : 23'd0);
                        scan <= {scan[9:0], 1'b0};

                        if (bitk == dunp - 4'd1)
                            st <= S_OUT;
                        else
                            bitk <= bitk + 4'd1;
                    end

                    // ----------------------------------------------------------------
                    // Consume decompressed result.
                    // ----------------------------------------------------------------
                    S_OUT: begin
                        if (in_c2) begin
                            aux_hi  <= 1'b0;
                            st      <= S_RXA;
                        end else begin
                            // 12-bit dres: buffer only the low byte; the high nibble
                            // can be read directly from the stable dres in S_ACC2.
                            out_low  <= dres[7:0];
                            out_cnt  <= 2'd2;
                            coef_cnt <= coef_cnt + 11'd1;
                            st       <= S_ACC;
                        end
                    end

                    // ----------------------------------------------------------------
                    // Receive 12-bit auxiliary word as two little-endian bytes.
                    // ----------------------------------------------------------------
                    S_RXA: if (wr_p) begin
                        if (!aux_hi) begin
                            aux[7:0] <= ui_in;
                            aux_hi   <= 1'b1;
                        end else begin
                            aux[11:8] <= ui_in[3:0];
                            aux_hi     <= 1'b0;
                            st         <= phase ? S_CLD : S_MSUB;
                        end
                    end

                    S_MSUB: begin
                        // Pass-1 v' coefficient is already stable on dres.
                        // Reduce it against the received auxiliary coefficient.
                        rem <= wmod;
                        st  <= S_CLD;
                    end

                    // ----------------------------------------------------------------
                    // Compress: restoring division by Q.
                    // ----------------------------------------------------------------
                    S_CLD: begin
                        // In pass 2, aux is the regenerated coefficient.
                        // In pass 1, S_MSUB has already loaded rem with wmod.
                        if (phase)
                            rem <= aux;
                        scan   <= 11'd0;
                        aux_hi <= 1'b0;
                        bitk   <= dop;
                        st     <= S_CMP;
                    end

                    S_CMP: begin
                        rem <= rem_next;

                        if (bitk == 0) begin
                            // Final iteration is the rounding bit; keep it in
                            // aux_hi while scan already contains the quotient bits.
                            aux_hi <= ge;
                            st     <= S_ACC;
                        end else begin
                            scan <= {scan[9:0], ge};
                            bitk <= bitk - 4'd1;
                        end
                    end

                    // ----------------------------------------------------------------
                    // Consume compression result.
                    // ----------------------------------------------------------------
                    S_ACC: begin
                        if (phase) begin
                            // Only equality matters, so keep a single sticky bit.
                            mismatch <= mismatch | (ycoef != cval);
                            coef_cnt <= coef_cnt + 11'd1;
                            st       <= S_UNP;
                        end else if (in_c2) begin
                            masm     <= {cval[0], masm[7:1]};
                            coef_cnt <= coef_cnt + 11'd1;

                            // For all supported ML-KEM parameter sets, u has a
                            // multiple-of-8 coefficient count, so coef_cnt[2:0]
                            // directly indexes the current message byte.
                            if (coef_cnt[2:0] == 3'd7) begin
                                out_cnt <= 2'd1;
                                st      <= S_ACC2;
                            end else begin
                                st <= S_UNP;
                            end
                        end else begin
                            st <= S_ACC2;
                        end
                    end

                    // ----------------------------------------------------------------
                    // Output staging.
                    // ----------------------------------------------------------------
                    S_ACC2: begin
                        if (out_cnt == 0) begin
                            st <= S_UNP;
                        end else if (rd_p) begin
                            case (out_cnt)
                                2'd1: begin
                                    out_cnt <= 2'd0; // message byte consumed
                                    st      <= S_UNP;
                                end
                                2'd2: begin
                                    out_cnt <= 2'd3; // coefficient high nibble next
                                end
                                default: begin
                                    out_cnt <= 2'd0; // coefficient high nibble consumed
                                    st      <= S_UNP;
                                end
                            endcase
                        end
                    end

                    // ----------------------------------------------------------------
                    // Parameter-derived integrity check.
                    // ----------------------------------------------------------------
                    S_FIN: begin
                        st <= S_DONE;
                    end

                    S_DONE: begin
                        // hold result until next start_p
                    end

                    default: st <= S_IDLE;
                endcase
            end
        end
    end

    // ------------------------------------------------------------------------
    // Status / outputs
    // ------------------------------------------------------------------------
    wire busy = !(st == S_IDLE || st == S_DONE || st == S_RXC ||
                  st == S_RXA || (st == S_ACC2 && out_cnt != 0));
    wire out_valid = (st == S_ACC2) && (out_cnt != 0);

    // Keep unused datapath storage electrically quiet before the first START.
    wire done_fault = (coef_cnt != n_tot);
    wire done_match = (~mismatch) && (coef_cnt == n_tot);
    assign uo_out  = (st == S_DONE) ? {6'd0, done_fault, done_match} :
                     (out_valid ?
                        ((out_cnt == 2'd1) ? masm :
                         (out_cnt == 2'd2) ? out_low :
                         {4'd0, dres[11:8]}) : 8'd0);
    assign uio_out = {((st == S_DONE) ? done_fault : 1'b0), busy, 6'd0};
    assign uio_oe  = 8'b1100_0000;

    // Compression result width mask. Fixed case avoids a variable-width shift.
    reg [10:0] dmask;
    always @(*) begin
        case (dop)
            4'd1:    dmask = 11'h001;
            4'd4:    dmask = 11'h00F;
            4'd5:    dmask = 11'h01F;
            4'd10:   dmask = 11'h3FF;
            default: dmask = 11'h7FF;
        endcase
    end

    // scan holds the quotient bits; aux_hi holds the final rounding bit.
    wire [11:0] cbase = {1'b0, scan} + {11'd0, aux_hi};
    wire [10:0] cval  = cbase[10:0] & dmask;

    // Explicitly consume otherwise-unused top-level inputs.
    wire _unused = &{ena, uio_in[7:6], 1'b0};

endmodule
