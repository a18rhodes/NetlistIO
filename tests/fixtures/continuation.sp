* Continuation line handling — + joins adjacent physical lines
.subckt rc_ladder in out gnd
R1 in mid1 1k
R2 mid1 mid2 2k
+ tc1=0.001 tc2=0.0001
R3 mid2 out 1k
C1 mid1 gnd 10p
C2 mid2 gnd 10p
.ends rc_ladder
