* Minimal SPICE netlist — voltage divider
.subckt voltage_divider in out gnd
R1 in mid 10k
R2 mid out 10k
C1 mid gnd 100n
.ends voltage_divider
