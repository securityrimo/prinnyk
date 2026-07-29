import struct


class NSFReader:

    def __init__(self, path):
        self.path = path
        self.data = open(path,"rb").read()

        self.size=len(self.data)

    def read_header(self):

        blob_size=struct.unpack_from("<I",self.data,4)[0]

        count=struct.unpack_from("<I",self.data,0x20)[0]

        table=[]

        pos=0x24

        for i in range(count):
            off=struct.unpack_from("<I",self.data,pos)[0]
            table.append(off)
            pos+=4

        return {
            "size":self.size,
            "blob_size":blob_size,
            "count":count,
            "table":table
        }
