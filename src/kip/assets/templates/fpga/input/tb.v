// Stimulus for Yosys's simulator: release reset, then offer one byte, 0x4B ('K').
module tb (input wire clk, output wire tx_line, output wire ready_line);
    reg  [3:0] step = 0;
    reg        rst_n = 0;
    reg        valid = 0;
    wire       ready, tx;
    always @(posedge clk) begin
        if (step != 4'd15) step <= step + 1;
        rst_n <= step >= 2;
        valid <= step >= 4 && step < 6;
    end
    uart_tx #(.CLK_HZ(12_000_000), .BAUD(115_200)) dut (
        .clk(clk), .rst_n(rst_n), .data(8'h4B), .valid(valid), .ready(ready), .tx(tx));
    assign tx_line = tx;
    assign ready_line = ready;
endmodule
