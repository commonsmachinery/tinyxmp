tinyxmp
=======

tinyxmp is a pure Python module for reading and writing metadata as raw
XMP packets. It is designed to have very few external dependencies
making it easily portable across platforms, server installations, etc.

Installation
------------

pip install https://github.com/commonsmachinery/tinyxmp/tarball/master

Usage
-----

    import tinyxmp
    x = tinyxmp.Metadata.load("webcam.png")
    x.get_xmp()
    x.write_xmp(xml_string)

Supported formats
-----------------

* JPEG (JFIF)
* PNG

Known limitations and TODOs
---------------------------

Extended XMP packets in JPEG are not supported. Trying to write
an XMP packet longer than 65502 bytes will result in exception.

Files are not locked while writing metadata.
