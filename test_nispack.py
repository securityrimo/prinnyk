from core.nispack import NISPack


p = NISPack(
    "workspace/iso/PSP_GAME/USRDIR/SCRIPT.DAT"
)


p.extract(
    "workspace/unpack/SCRIPT"
)
