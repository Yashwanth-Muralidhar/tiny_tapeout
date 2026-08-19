`default_nettype none


// tt_um_vinayaka_pqc_fo_v7 -- SAFE optimization subset applied:
//   OPT1: FSM binary encoding attribute (kept)
//   OPT7: S_FIN state removed (folded into direct S_DONE transition)
//   OPT8: uo_out output mux refactored to intermediate wire
// Functionality and novelty (coeff-count integrity check) unchanged.


module tt_um_vinayaka_pqc_fo_v7 (
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


    wire       wr_i    = uio_in[0];
    wire       start_i = uio_in[1];
    wire       rd_i    = uio_in[2];
    wire       phase_i = uio_in[3];
    wire [1:0] pr_i    = uio_in[5:4];


    reg wr_q, start_q, rd_q;
    reg phase_r;
    reg [1:0] pr_r;
    wire       phase = phase_r;
    wire [1:0] pr = pr_r;
    wire wr_p    = wr_i    & ~wr_q;
    wire start_p = start_i & ~start_q;
    wire rd_p    = rd_i    & ~rd_q;


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
        S_DONE = 4'd12;   // OPT7: S_FIN (4'd11) removed


    reg [22:0] acc;
    reg [11:0] rem;
    reg [10:0] scan;
    reg [17:0] buf_r;
    reg [4:0]  nbits;
    reg [10:0] byte_cnt, coef_cnt;
    reg [10:0] ycoef;
    reg [11:0] aux;
    reg [3:0]  bitk;
    reg        mismatch;
    reg [7:0]  out_low;
    reg [1:0]  out_cnt;
    reg        aux_hi;
    reg [7:0]  masm;
    reg        in_c2;


    wire [3:0] dunp = in_c2 ? dv : du;
    wire [3:0] dop  = (~phase & in_c2) ? 4'd1 : dunp;


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


    wire [12:0] wsub = {1'b0, dres} - {1'b0, aux};
    wire [11:0] wmod = wsub[12] ? (wsub[11:0] + Q) : wsub[11:0];


    wire [11:0] rem_shift = {rem[10:0], 1'b0};
    wire        ge        = (rem >= 12'd1665);
    wire [11:0] rem_next  = ge ? (rem_shift - Q) : rem_shift;


    always @(posedge clk) begin
        if (!rst_n) begin
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
                buf_r    <= 18'd0;
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
                    end


                    S_RXC: if (wr_p) begin
                        case (nbits)
                            5'd0:  buf_r <= buf_r | {10'd0, ui_in};
                            5'd1:  buf_r <= buf_r | {9'd0,  ui_in, 1'd0};
                            5'd2:  buf_r <= buf_r | {8'd0,  ui_in, 2'd0};
                            5'd3:  buf_r <= buf_r | {7'd0,  ui_in, 3'd0};
                            5'd4:  buf_r <= buf_r | {6'd0,  ui_in, 4'd0};
                            5'd5:  buf_r <= buf_r | {5'd0,  ui_in, 5'd0};
                            5'd6:  buf_r <= buf_r | {4'd0,  ui_in, 6'd0};
                            5'd7:  buf_r <= buf_r | {3'd0,  ui_in, 7'd0};
                            5'd8:  buf_r <= buf_r | {2'd0,  ui_in, 8'd0};
                            5'd9:  buf_r <= buf_r | {1'd0,  ui_in, 9'd0};
                            5'd10: buf_r <= buf_r | {ui_in, 10'd0};
                            default: buf_r <= buf_r;
                        endcase
                        nbits    <= nbits + 5'd8;
                        byte_cnt <= byte_cnt + 11'd1;
                        st       <= S_UNP;
                    end


                    S_UNP: begin
                        if (nbits >= {1'b0, dunp}) begin
                            ycoef <= ynew;


                            case (dunp)
                                4'd4:    buf_r <= {4'd0,  buf_r[17:4]};
                                4'd5:    buf_r <= {5'd0,  buf_r[17:5]};
                                4'd10:   buf_r <= {10'd0, buf_r[17:10]};
                                default: buf_r <= {11'd0, buf_r[17:11]};
                            endcase


                            nbits <= nbits - {1'b0, dunp};


                            if (phase) begin
                                aux_hi <= 1'b0;
                                st     <= S_RXA;
                            end else begin
                                acc  <= 23'd0;
                                scan <= pres;
                                bitk <= 4'd0;
                                st   <= S_DEC;
                            end
                        end else if (byte_cnt == cx_len) begin
                            st <= S_DONE;          // OPT7: was S_FIN
                        end else begin
                            if (byte_cnt == c1_len) begin
                                in_c2 <= 1'b1;
                                buf_r <= 18'd0;
                                nbits <= 5'd0;
                            end
                            st <= S_RXC;
                        end
                    end


                    S_DEC: begin
                        acc  <= {acc[21:0], 1'b0} +
                                (scan[10] ? {11'd0, Q} : 23'd0);
                        scan <= {scan[9:0], 1'b0};


                        if (bitk == dunp - 4'd1)
                            st <= S_OUT;
                        else
                            bitk <= bitk + 4'd1;
                    end


                    S_OUT: begin
                        if (in_c2) begin
                            aux_hi  <= 1'b0;
                            st      <= S_RXA;
                        end else begin
                            out_low  <= dres[7:0];
                            out_cnt  <= 2'd2;
                            coef_cnt <= coef_cnt + 11'd1;
                            st       <= S_ACC;
                        end
                    end


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
                        rem <= wmod;
                        st  <= S_CLD;
                    end


                    S_CLD: begin
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
                            aux_hi <= ge;
                            st     <= S_ACC;
                        end else begin
                            scan <= {scan[9:0], ge};
                            bitk <= bitk - 4'd1;
                        end
                    end


                    S_ACC: begin
                        if (phase) begin
                            mismatch <= mismatch | (ycoef != cval);
                            coef_cnt <= coef_cnt + 11'd1;
                            st       <= S_UNP;
                        end else if (in_c2) begin
                            masm     <= {cval[0], masm[7:1]};
                            coef_cnt <= coef_cnt + 11'd1;


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


                    S_ACC2: begin
                        if (out_cnt == 0) begin
                            st <= S_UNP;
                        end else if (rd_p) begin
                            case (out_cnt)
                                2'd1: begin
                                    out_cnt <= 2'd0;
                                    st      <= S_UNP;
                                end
                                2'd2: begin
                                    out_cnt <= 2'd3;
                                end
                                default: begin
                                    out_cnt <= 2'd0;
                                    st      <= S_UNP;
                                end
                            endcase
                        end
                    end


                    S_DONE: begin
                    end


                    default: st <= S_IDLE;
                endcase
            end
        end
    end


    wire busy = !(st == S_IDLE || st == S_DONE || st == S_RXC ||
                  (st == S_ACC2 && out_cnt != 0));
    wire out_valid = (st == S_ACC2) && (out_cnt != 0);


    wire done_fault = (coef_cnt != n_tot);
    wire done_match = (~mismatch) && (coef_cnt == n_tot);


    // OPT8: output byte-select refactored to intermediate wire (identical logic)
    wire [7:0] out_mux = (out_cnt == 2'd1) ? masm :
                         (out_cnt == 2'd2) ? out_low :
                                             {4'd0, dres[11:8]};


    assign uo_out  = (st == S_DONE) ? {6'd0, done_fault, done_match} :
                     (out_valid ? out_mux : 8'd0);
    assign uio_out = {((st == S_DONE) ? done_fault : 1'b0), busy, 6'd0};
    assign uio_oe  = 8'b1100_0000;


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


    wire [11:0] cbase = {1'b0, scan} + {11'd0, aux_hi};
    wire [10:0] cval  = cbase[10:0] & dmask;


    wire _unused = &{ena, uio_in[7:6], 1'b0};


endmodule
