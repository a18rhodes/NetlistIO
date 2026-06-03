* CMOS inverter — NMOS/PMOS detection from model names
.subckt inv in out vdd vss
M1 out in vdd vdd pmos w=2e-6 l=1.5e-7
M2 out in vss vss nmos w=1e-6 l=1.5e-7
.ends inv
