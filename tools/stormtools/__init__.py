"""Toolchain for moving CyberConnect2 / CriWare data into the Storm Android port.

Entry points
------------
``cpk``       inspect and extract CriWare CPK archives
``scan``      locate NUCC / NTP3 / NDP3 / @UTF signatures inside a blob
``pack``      convert glTF 2.0 into engine ``.smesh`` / ``.sanm`` packages
``demo``      regenerate the built-in, legally clean demo fighters and arena
"""

from .binary import BinaryError, Reader, Writer, fnv1a32
from .cpk import Cpk, CpkError, CpkEntry, open_cpk
from .formats import AnimClip, Bone, MeshAsset, read_anim, read_mesh, write_anim, write_mesh
from .pack import PackError, pack_glb
from .scan import scan_file

__version__ = "0.1.0"

__all__ = [
    "AnimClip",
    "BinaryError",
    "Bone",
    "Cpk",
    "CpkEntry",
    "CpkError",
    "MeshAsset",
    "PackError",
    "Reader",
    "Writer",
    "fnv1a32",
    "open_cpk",
    "pack_glb",
    "read_anim",
    "read_mesh",
    "scan_file",
    "write_anim",
    "write_mesh",
    "__version__",
]
