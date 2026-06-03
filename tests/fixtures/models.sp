* .model directives inside and outside subckts
.model nmos_fast nmos level=54 tox=7e-9 ngate=1e20
.model pmos_fast pmos level=54 tox=7e-9

.subckt inv_fast in out vdd vss
.model local_d diode is=1e-14
M1 out in vdd vdd pmos_fast w=2u l=100n
M2 out in vss vss nmos_fast w=1u l=100n
D1 out vdd local_d
.ends inv_fast
