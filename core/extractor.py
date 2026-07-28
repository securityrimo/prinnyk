import subprocess
from pathlib import Path

def extract_iso(iso_path, outdir):

    outdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "7z",
        "x",
        str(iso_path),
        f"-o{outdir}",
        "-y"
    ]

    subprocess.run(cmd, check=True)
