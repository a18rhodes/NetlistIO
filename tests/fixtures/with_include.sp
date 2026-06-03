* Netlist that references a .lib section
.lib "lib_sections.lib" tt

.subckt inv in out vdd vss
M1 out in vdd vdd pmos_tt w=2u l=100n
M2 out in vss vss nmos_tt w=1u l=100n
.ends inv
