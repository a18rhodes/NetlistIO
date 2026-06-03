* Standard cell library — no top-level instances (library-only file)
.subckt nand2 a b out vdd vss
M1 out a vdd vdd pmos w=2u l=100n
M2 out b vdd vdd pmos w=2u l=100n
M3 mid a vss vss nmos w=1u l=100n
M4 out b mid vss nmos w=1u l=100n
.ends nand2

.subckt nor2 a b out vdd vss
M1 out a vdd vdd pmos w=1u l=100n
M2 out b mid vdd pmos w=1u l=100n
M3 out a vss vss nmos w=2u l=100n
M4 out b vss vss nmos w=2u l=100n
.ends nor2
