* Two-level CMOS hierarchy with top-level instantiation
.subckt inv in out vdd vss
M1 out in vdd vdd pmos w=2u l=100n
M2 out in vss vss nmos w=1u l=100n
.ends inv

.subckt buf in out vdd vss
X1 in mid vdd vss inv
X2 mid out vdd vss inv
.ends buf

Xbuf_inst a b vdd vss buf
