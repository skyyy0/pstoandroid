#!/usr/bin/env python3
"""Command line front-end for the Storm asset pipeline.

Examples
--------
    python -m stormtools cpk list data.cpk
    python -m stormtools cpk extract data.cpk out/ --only chara --ext .xfbin
    python -m stormtools scan out/chara/naruto.xfbin
    python -m stormtools pack chara/naruto.glb out/ --name naruto --manifest out/manifest.txt
    python -m stormtools demo --target android/app/src/main
    python -m stormtools info out/naruto.smesh
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from . import demo_assets
from .cpk import CpkError, open_cpk
from .formats import describe_mesh, read_anim, read_mesh
from .pack import PackError, pack_glb
from .scan import scan_file


def _cmd_cpk_list(args) -> int:
    try:
        cpk = open_cpk(args.archive)
    except (CpkError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    entries = cpk.find(args.filter) if args.filter else cpk.entries
    for entry in entries:
        flag = "crilayla" if entry.compressed else "raw"
        print(f"{entry.path:70s} {entry.size:>10d} {flag}")
    print(f"-- {len(entries)} / {len(cpk)} entries")
    return 0


def _cmd_cpk_extract(args) -> int:
    try:
        cpk = open_cpk(args.archive)
    except (CpkError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    extensions = args.ext.split(",") if args.ext else None
    written = cpk.extract_all(args.destination, only=args.only, extensions=extensions,
                              limit=args.limit)
    print(f"extracted {len(written)} file(s) to {args.destination}")
    return 0


def _cmd_scan(args) -> int:
    for path in args.paths:
        if not os.path.exists(path):
            print(f"error: {path} not found", file=sys.stderr)
            continue
        result = scan_file(path)
        print(result.summary())
        if args.verbose:
            for hit in result.hits:
                print(f"  {hit.offset:08x}  {hit.signature.decode('latin-1'):10s} {hit.description}")
    return 0


def _cmd_pack(args) -> int:
    for source in args.inputs:
        try:
            info = pack_glb(
                source,
                args.destination,
                base_name=args.name if len(args.inputs) == 1 else None,
                manifest_path=args.manifest,
                scale=args.scale,
            )
        except (PackError, Exception) as exc:  # noqa: BLE001 - surfaced to the user
            print(f"error: {source}: {exc}", file=sys.stderr)
            return 1
        print(f"{os.path.basename(info['mesh'])}: {info['vertices']} verts, "
              f"{info['triangles']} tris, {info['bones']} bones, clips={info['clips']}")
    return 0


def _cmd_info(args) -> int:
    for path in args.paths:
        with open(path, "rb") as handle:
            data = handle.read()
        if data[:4] == b"SMSH":
            print(f"{path}: {describe_mesh(read_mesh(data))}")
        elif data[:4] == b"SANM":
            clip = read_anim(data)
            keys = sum(len(track.keys) for track in clip.tracks)
            print(f"{path}: clip={clip.name} duration={clip.duration:.2f}s "
                  f"tracks={len(clip.tracks)} keys={keys} loop={clip.loop}")
        else:
            print(f"{path}: unknown package magic {data[:4]!r}")
    return 0


def _cmd_demo(args) -> int:
    result = demo_assets.write_demo_assets(
        os.path.join(args.target, "assets", "storm"),
        os.path.join(args.target, "assets", "storm", "manifest.txt"),
    )
    print(f"wrote {len(result['files'])} asset file(s) + manifest to {args.target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stormtools", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    cpk = subparsers.add_parser("cpk", help="inspect/extract CriWare CPK archives")
    cpk_sub = cpk.add_subparsers(dest="cpk_command", required=True)
    cpk_list = cpk_sub.add_parser("list", help="list archive entries")
    cpk_list.add_argument("archive")
    cpk_list.add_argument("--filter", default=None)
    cpk_list.set_defaults(func=_cmd_cpk_list)
    cpk_extract = cpk_sub.add_parser("extract", help="extract archive entries")
    cpk_extract.add_argument("archive")
    cpk_extract.add_argument("destination")
    cpk_extract.add_argument("--only", default=None)
    cpk_extract.add_argument("--ext", default=None, help="comma separated extension filter")
    cpk_extract.add_argument("--limit", type=int, default=0)
    cpk_extract.set_defaults(func=_cmd_cpk_extract)

    scan = subparsers.add_parser("scan", help="locate CC2/CriWare signatures in files")
    scan.add_argument("paths", nargs="+")
    scan.add_argument("-v", "--verbose", action="store_true")
    scan.set_defaults(func=_cmd_scan)

    pack = subparsers.add_parser("pack", help="convert glTF 2.0 to .smesh/.sanm")
    pack.add_argument("inputs", nargs="+")
    pack.add_argument("destination")
    pack.add_argument("--name", default=None)
    pack.add_argument("--manifest", default=None)
    pack.add_argument("--scale", type=float, default=1.0)
    pack.set_defaults(func=_cmd_pack)

    info = subparsers.add_parser("info", help="describe .smesh/.sanm packages")
    info.add_argument("paths", nargs="+")
    info.set_defaults(func=_cmd_info)

    demo = subparsers.add_parser("demo", help="regenerate built-in demo assets")
    demo.add_argument("--target", default="android/app/src/main")
    demo.set_defaults(func=_cmd_demo)
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
