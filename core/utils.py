import hashlib

def sha1(path):
    h = hashlib.sha1()

    with open(path, "rb") as f:
        while True:
            data = f.read(1024 * 1024)
            if not data:
                break
            h.update(data)

    return h.hexdigest()
