# tinyxmp - pure Python module for reading and writing raw XMP packets
#
# Copyright 2014 Commons Machinery http://commonsmachinery.se/
#
# Authors: Artem Popov <artfwo@commonsmachinery.se>
#
# Distributed under an GPLv2 license, please see LICENSE in the top dir.

import os, shutil
import uuid
import struct
import zlib
import tempfile

class XMPError(Exception):
    pass


def wrap_packet(rdf, guid=None):
    if guid is None:
        guid = uuid.uuid4().hex.encode()
    bom = b'\xef\xbb\xbf'
    return (b'<?xpacket begin="%s" id="%s"?>' % (bom, guid) + \
           b'<x:xmpmeta xmlns:x="adobe:ns:meta/">' + \
           bytes(rdf) + \
           b'</x:xmpmeta>' + \
           b'<?xpacket end="w"?>')

def unwrap_packet(xmp):
    rdf_start = xmp.find(b"<rdf:RDF")
    rdf_end = xmp.find(b"</rdf:RDF>") + 10
    return xmp[rdf_start:rdf_end]

def packet_is_wrapped(xmp):
    return xmp.count(b"<?xpacket") == 2

# TODO: deal with unwrapped packets
def pad_packet(xmp, size):
    if len(xmp) > size:
        raise XMPError("XMP packet too big to fit specified size")
    delta = size - len(xmp)
    packet_end = xmp.rfind(b"<?xpacket")
    left = xmp[:packet_end]
    right = xmp[packet_end:]

    pad = bytearray(b' ' * delta)
    for i in range(0, len(pad), 80):
        pad[i] = ord(b'\n')
    pad[-1] = ord(b'\n')

    return (left + bytes(pad) + right)


class Metadata(object):
    def __init__(self, filename):
        self.filename = filename
        self._process()

        # padded packet as saved in the original file
        self._xmp = None

    def has_xmp(self):
        return bool(self._xmp)

    def get_xmp(self):
        return self._xmp[:]

    def write_xmp(self, new_xmp):
        self._process(new_xmp)

    def _process(self, new_xmp=None):
        raise NotImplementedError

    @staticmethod
    def load(path):
        name, ext = os.path.splitext(path)
        ext = ext.lower()
        if ext.endswith(".jpg") or ext.endswith(".jpeg"):
            return JpegMetadata(path)
        elif ext.endswith(".png"):
            return PngMetadata(path)
        else:
            raise XMPError("Couldn't find XMP parser for %s" % path)


class JpegMetadata(Metadata):
    def __init__(self, filename):
        super(JpegMetadata, self).__init__(filename)
        #self._process()

    # read/write xmp packet
    def _process(self, new_xmp=None):
        f = open(self.filename, "r+b")
        temp = None

        file_pos = 0
        xmp_seg_pos = 0
        xmp_seg_size = 0
        xmp_packet = ''

        magic = f.read(2)
        if magic != b'\377\330':
            raise XMPError("File %s is not a JPEG file" % f.name)

        # write xmp in the very beginning of the file
        # if no other application segments are found below
        xmp_seg_pos = f.tell()

        try:
            # scan for exif/xmp
            while True:
                file_pos = f.tell()
                seg_type, seg_length, seg_data = self._read_segment(f)
                # APP0
                if seg_type == 0xe0:
                    xmp_seg_pos = f.tell()
                # APP1 EXIF
                elif seg_type == 0xe1 and seg_data.startswith('Exif\x00\x00'):
                    xmp_seg_pos = f.tell()
                # APP1 XMP
                elif seg_type == 0xe1 and seg_data.startswith("http://ns.adobe.com/xap/1.0/\x00"):
                    xmp_seg_pos = file_pos
                    xmp_seg_size = seg_length
                    xmp_packet = seg_data[29:] # strip namespace
                    break
                elif seg_type == 0xda: # SOS
                    break

            # write xmp
            if new_xmp:
                if xmp_seg_pos == 0:
                    raise XMPError("Couldn't find position to insert XMP packet")

                if not packet_is_wrapped(new_xmp):
                    new_xmp = wrap_packet(new_xmp)

                # TODO: support ExtendedXMP
                if len(new_xmp) > 65502:
                    raise XMPError("Can't write XMP packet longer than 65502 bytes")

                if len(new_xmp) > len(xmp_packet):
                    # write to temporary file first
                    temp = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
                    f.seek(0)
                    buf = f.read(xmp_seg_pos)
                    temp.write(buf)

                    new_xmp = pad_packet(new_xmp, (len(new_xmp) // 4000 + 1) * 4000)
                    self._write_segment(temp, 0xe1, b"http://ns.adobe.com/xap/1.0/\x00" + new_xmp)

                    f.seek(xmp_seg_size, 1)
                    buf = f.read()
                    temp.write(buf)

                    f.close(); temp.close()
                    os.unlink(self.filename)
                    shutil.move(temp.name, self.filename)
                else:
                    # write in place
                    f.seek(xmp_seg_pos)
                    new_xmp = pad_packet(new_xmp, len(xmp_packet))
                    self._write_segment(f, 0xe1, b"http://ns.adobe.com/xap/1.0/\x00" + new_xmp)

                xmp_packet = new_xmp

            if xmp_packet:
                self._xmp = unwrap_packet(xmp_packet)
        finally:
            f.close()
            if temp:
                temp.close()

    def _read_segment(self, f):
        magic = f.read(1)
        if magic != b'\xff':
            raise XMPError("Invalid JPEG segment")
        (type, ) = struct.unpack("B", f.read(1))
        (length, ) = struct.unpack(">H", f.read(2))
        data = f.read(length - 2)
        return type, length, data

    def _write_segment(self, f, type, data):
        segment = struct.pack(">cBH%ds" % len(data), b'\xff', type, len(data) + 2, data)
        f.write(segment)


class PngMetadata(Metadata):
    def __init__(self, filename):
        super(PngMetadata, self).__init__(filename)
        #self._process()

    # read/write xmp packet
    def _process(self, new_xmp=None):
        f = open(self.filename, "rb")

        file_pos = 0
        xmp_seg_pos = 0
        xmp_seg_size = 0
        xmp_packet = ''

        magic = f.read(8)
        if magic != b'\x89PNG\r\n\x1a\n':
            raise XMPError("File %s is not a PNG file!" % f.name)

        try:
            # scan for xmp
            while True:
                file_pos = f.tell()
                chunk_length, chunk_type, chunk_data, chunk_crc = self._read_chunk(f)

                if chunk_type == "IHDR":
                    xmp_seg_pos = f.tell()
                elif chunk_type == "iTXt" and chunk_data.startswith(b'XML:com.adobe.xmp\x00\x00\x00\x00\x00'):
                    xmp_seg_pos = file_pos
                    xmp_seg_size = chunk_length + 12
                    xmp_packet = chunk_data[22:] # strip namespace
                    break
                elif chunk_type == "IEND":
                    break
        finally:
            f.close()

        # write xmp
        if new_xmp:
            if xmp_seg_pos == 0:
                raise XMPError("Couldn't find position to insert XMP packet")

            if not packet_is_wrapped(new_xmp):
                new_xmp = wrap_packet(new_xmp)

            if len(new_xmp) > len(xmp_packet):
                # write to temporary file first
                try:
                    f = open(self.filename, "rb")
                    temp = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
                    f.seek(0)
                    buf = f.read(xmp_seg_pos)
                    temp.write(buf)

                    new_xmp = pad_packet(new_xmp, (len(new_xmp) // 4000 + 1) * 4000)
                    self._write_chunk(temp, "iTXt", b'XML:com.adobe.xmp\x00\x00\x00\x00\x00' + new_xmp)

                    f.seek(xmp_seg_size, 1)
                    buf = f.read()
                    temp.write(buf)

                    f.close(); temp.close()
                    os.unlink(self.filename)
                    shutil.move(temp.name, self.filename)
                finally:
                    f.close()
                    temp.close()
            else:
                try:
                    # write in place
                    f = open(self.filename, "r+b")
                    f.seek(xmp_seg_pos)
                    new_xmp = pad_packet(new_xmp, len(xmp_packet))
                    self._write_chunk(f, "iTXt", b'XML:com.adobe.xmp\x00\x00\x00\x00\x00' + new_xmp)
                finally:
                    f.close()

            xmp_packet = new_xmp

        if xmp_packet:
            self._xmp = unwrap_packet(xmp_packet)

    def _read_chunk(self, f):
        (chunk_length, ) = struct.unpack(">I", f.read(4))
        chunk_type = f.read(4)
        chunk_data = f.read(chunk_length)
        (chunk_crc, ) = struct.unpack(">I", f.read(4))

        if zlib.crc32(chunk_type + chunk_data) & 0xffffffff != chunk_crc:
            raise XMPError("Checksum error while reading PNG file %s" % f.name)

        return (chunk_length, chunk_type, chunk_data, chunk_crc)

    def _write_chunk(self, f, type, data):
        chunk = struct.pack(">I4s%dsI" % len(data), len(data), type, data, zlib.crc32(type + data) & 0xffffffff)
        f.write(chunk)
