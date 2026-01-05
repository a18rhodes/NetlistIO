* NetlistIO Spice Test Netlist
X1 a b c cell_0
X2 a b c cell_1
R1 a b 10k
M1 b c 0 0 nmos w=1u l=0.1u
.SUBCKT cell_0 a b c
R1 a b 10k
M1 b c 0 0 nmos w=1u l=0.1u
.ENDS
.SUBCKT cell_1 a b c
R1 a b 10k
M1 b c 0 0 nmos w=1u l=0.1u
.ENDS
X3 a b c cell_1
X4 a b c cell_0
R2 a b 10k
M2 b c 0 0 nmos w=1u l=0.1u
