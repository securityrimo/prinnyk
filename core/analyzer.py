from pathlib import Path
import hashlib
import math
import json
from collections import Counter


MAGIC = {
    b"\x1f\x8b": "gzip",
    b"\x78\x9c": "zlib",
    b"\x78\xda": "zlib",
    b"BZh": "bzip2",
    b"\xfd7zXZ": "lzma",
    b"PK\x03\x04": "zip",
}

def sha1(path):

    h = hashlib.sha1()

    with open(path,"rb") as f:

        while True:

            b=f.read(1024*1024)

            if not b:
                break

            h.update(b)

    return h.hexdigest()

def md5(path):

    h=hashlib.md5()

    with open(path,"rb") as f:

        while True:

            b=f.read(1024*1024)

            if not b:
                break

            h.update(b)

    return h.hexdigest()

def entropy(data):

    if not data:
        return 0

    c=Counter(data)

    n=len(data)

    e=0

    for v in c.values():

        p=v/n

        e-=p*math.log2(p)

    return round(e,3)

def ascii_strings(data,minlen=4):

    count=0

    cur=[]

    for b in data:

        if 32<=b<=126:

            cur.append(b)

        else:

            if len(cur)>=minlen:
                count+=1

            cur=[]

    return count

def sjis_strings(data,minlen=4):

    count=0

    i=0

    while i<len(data):

        buf=[]

        while i<len(data):

            b=data[i]

            if 0x20<=b<=0x7e:

                buf.append(b)

                i+=1

                continue

            if (
                (0x81<=b<=0x9f)
                or
                (0xe0<=b<=0xfc)
            ):

                if i+1>=len(data):
                    break

                c=data[i+1]

                if (
                    0x40<=c<=0xfc
                    and c!=0x7f
                ):

                    buf.extend([b,c])

                    i+=2

                    continue

            break

        if len(buf)>=minlen:
            count+=1

        i+=1

    return count

def detect_magic(data):

    for k,v in MAGIC.items():

        if data.startswith(k):

            return v

    return "unknown"

def analyze_file(path):

    data=path.read_bytes()

    return {

        "file":str(path),

        "size":len(data),

        "sha1":sha1(path),

        "md5":md5(path),

        "entropy":entropy(data),

        "ascii":ascii_strings(data),

        "sjis":sjis_strings(data),

        "magic":detect_magic(data)
    }

def analyze_directory(root):

    result=[]

    root=Path(root)

    files=list(root.rglob("*"))

    files=[x for x in files if x.is_file()]

    total=len(files)

    for n,f in enumerate(files,1):

        print(f"[{n}/{total}] {f.name}")

        result.append(
            analyze_file(f)
        )

    return result
