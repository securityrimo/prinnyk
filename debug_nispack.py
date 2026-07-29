from pathlib import Path
import struct


data = Path(
    "workspace/iso/PSP_GAME/USRDIR/SCRIPT.DAT"
).read_bytes()


print("HEADER")
print(data[:16])


count = struct.unpack(
    "<I",
    data[12:16]
)[0]


print("COUNT =", count)


print("\nHEX TABLE")


for pos in range(0x10,0x100,0x10):

    chunk=data[pos:pos+16]

    print(
        hex(pos),
        chunk.hex(" ")
    )
