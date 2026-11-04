// UART transmitter: 8 data bits, no parity, one stop bit (8N1), LSB first.
module uart_tx #(
    parameter integer CLK_HZ = 12_000_000,  // system clock frequency
    parameter integer BAUD   = 115_200      // line rate
) (
    input  wire       clk,    // system clock
    input  wire       rst_n,  // synchronous reset, active low
    input  wire [7:0] data,   // byte to send, held while valid
    input  wire       valid,  // a byte is offered
    output wire       ready,  // idle: the next byte may be offered
    output reg        tx      // serial line, idle high
);
    localparam integer DIV = (CLK_HZ + BAUD / 2) / BAUD;  // clocks per bit, rounded

    reg [$clog2(DIV)-1:0] count;
    reg [3:0]             bit_index;
    reg [9:0]             frame;   // stop, data[7:0], start
    reg                   busy;

    assign ready = !busy;

    always @(posedge clk) begin
        if (!rst_n) begin
            busy  <= 1'b0;
            tx    <= 1'b1;
            count <= 0;
            bit_index <= 0;
        end else if (!busy) begin
            if (valid) begin
                frame <= {1'b1, data, 1'b0};
                busy  <= 1'b1;
                count <= 0;
                bit_index <= 0;
                tx    <= 1'b0;   // start bit
            end
        end else if (count == DIV - 1) begin
            count <= 0;
            if (bit_index == 9) begin
                busy <= 1'b0;
                tx   <= 1'b1;
            end else begin
                bit_index <= bit_index + 1;
                tx <= frame[bit_index + 1];
            end
        end else begin
            count <= count + 1;
        end
    end
endmodule
