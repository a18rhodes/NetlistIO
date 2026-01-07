import sys
import traceback

from netlistio import get_netlist, NetlistFormat

try:
    netlist = get_netlist("./tests/data/synthetic/small_basic.sp", NetlistFormat.SPICE)
    print(f"Got netlist: {netlist}")
    if netlist:
        netlist.write(sys.stdout)
    else:
        print("ERROR: netlist is None")
except Exception as e:
    print(f"Exception occurred: {e}")
    traceback.print_exc()
