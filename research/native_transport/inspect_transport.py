"""Offline x86 PE, Go pclntab and import/xref inspection for the IMO transport."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct

import capstone
import pefile


GO_HEADER = bytes.fromhex("f1ffffff00000104")
DISASSEMBLER = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
DISASSEMBLER.detail = True


def image_base(image):
    return image.OPTIONAL_HEADER.ImageBase


def read_image(path):
    image = pefile.PE(str(path), fast_load=True)
    if image.FILE_HEADER.Machine != 0x14C:
        raise ValueError(f"Expected x86 PE: {path.name}")
    image.parse_data_directories(directories=[0, 1, 5, 13, 14])
    return image


def instructions(image, rva, count):
    return DISASSEMBLER.disasm(image.get_data(rva, count), image_base(image) + rva)


def sections(image, characteristic):
    return [(section.VirtualAddress, section.VirtualAddress + section.Misc_VirtualSize)
            for section in image.sections if section.Characteristics & characteristic]


def in_ranges(value, ranges):
    return any(start <= value < end for start, end in ranges)


def pe_summary(path, image):
    imports = {}
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        imports[attr] = {
            lib.dll.decode("ascii"): len(lib.imports) for lib in getattr(image, attr, [])
        }
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "machine": hex(image.FILE_HEADER.Machine),
        "image_base": hex(image_base(image)),
        "coff_symbols": image.FILE_HEADER.NumberOfSymbols,
        "clr_rva": hex(image.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress),
        "import_libraries": imports,
        "exports": [
            {"name": item.name.decode("ascii") if item.name else None,
             "ordinal": item.ordinal, "rva": hex(item.address), "forwarder":
                 item.forwarder.decode("ascii") if item.forwarder else None}
            for item in image.DIRECTORY_ENTRY_EXPORT.symbols
        ],
    }


def pclntab(image, data):
    origin = data.find(GO_HEADER)
    if origin < 0:
        raise ValueError("Go 1.20+ little-endian x86 pclntab not found")
    count, _, text, names, _, _, _, table = struct.unpack_from("<8I", data, origin + 8)
    if not (0 < count < 100_000 and 0 < names < table and origin + table + count * 8 < len(data)):
        raise ValueError("Invalid pclntab offsets")
    functions = {}
    for index in range(count):
        entry, function = struct.unpack_from("<II", data, origin + table + index * 8)
        if origin + table + function + 8 > len(data):
            raise ValueError("Invalid function entry")
        name_offset = struct.unpack_from("<i", data, origin + table + function + 4)[0]
        start = origin + names + name_offset
        if not origin + names <= start < origin + table:
            raise ValueError("Invalid function name offset")
        end = data.index(b"\0", start, origin + table)
        functions[text + entry] = data[start:end].decode("utf-8")
    if len(functions) != count or not in_ranges(text - image_base(image), sections(image, 0x20000000)):
        raise ValueError("Invalid pclntab text entries")
    return image.get_rva_from_offset(origin), functions


def go_report(path, image):
    table_rva, functions = pclntab(image, path.read_bytes())
    base = image_base(image)
    functions_by_rva = {address - base: name for address, name in functions.items()}
    ordered = sorted(functions_by_rva)
    exports = []
    for item in image.DIRECTORY_ENTRY_EXPORT.symbols:
        if not item.name or not item.name.startswith(b"gonet_"):
            continue
        trampoline = None
        stack_offsets = set()
        ret = None
        for insn in instructions(image, item.address, 400):
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_IMM:
                    target = functions.get(op.imm)
                    if target and target.startswith("_cgoexp_"):
                        trampoline = target
                if (op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_EBP
                        and op.mem.disp >= 8):
                    stack_offsets.add(hex(op.mem.disp))
            if insn.mnemonic == "ret":
                ret = insn.op_str or "plain"
                break
        if not trampoline or not ret:
            raise ValueError(f"Unrecognized cgo wrapper for {item.name!r}")
        exports.append({"export": item.name.decode(), "entry_rva": hex(item.address),
                        "go_trampoline": trampoline, "ebp_stack_operands": sorted(stack_offsets, key=lambda x: int(x, 16)),
                        "ret": ret})

    selected = []
    for start, end in zip(ordered, ordered[1:]):
        name = functions_by_rva[start]
        if not re.match(r"^(?:main\.(?:gonet_|\(\*(?:httpClient|httpStreaming|wsClient|tlsSocket|connCbWrapper|httpCbWrapper)\)\.[A-Z]|newQuicConn)|_cgoexp_)", name):
            continue
        calls = []
        indirect = 0
        for insn in instructions(image, start, end - start):
            if insn.mnemonic != "call":
                continue
            operand = insn.operands[0]
            if operand.type != capstone.x86.X86_OP_IMM:
                indirect += 1
                continue
            target = functions.get(operand.imm, "")
            if target and target != name and not target.startswith(("runtime.", "fmt.")) and target not in calls:
                calls.append(target)
        selected.append({"rva": hex(start), "function": name,
                         "direct_calls": calls, "indirect_calls": indirect})
    return {"pclntab_rva": hex(table_rva), "recovered_functions": len(functions),
            "wrappers": exports, "selected_functions": selected}


def relocation_xrefs(image):
    refs = defaultdict(list)
    for block in image.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.type == 3:
                data = image.get_data(entry.rva, 4)
                if len(data) == 4:
                    refs[struct.unpack("<I", data)[0] - image_base(image)].append(entry.rva)
    return refs


def proxy_report(path, image, go_image, refs):
    imports = {item.address: item.name.decode() for lib in image.DIRECTORY_ENTRY_IMPORT
               for item in lib.imports if item.name}
    code = sections(image, 0x20000000)
    data = path.read_bytes()
    labels = {entry.name.decode(): entry.name + b"\0" for entry in go_image.DIRECTORY_ENTRY_EXPORT.symbols
              if entry.name and entry.name.startswith(b"gonet_")}
    labels["libgonet.dll"] = "libgonet.dll\0".encode("utf-16le")
    hits = []
    for name, encoded in labels.items():
        for match in re.finditer(re.escape(encoded), data):
            # Include an identifier boundary to exclude suffixes inside longer ASCII strings.
            if name != "libgonet.dll" and match.start() > 0 and data[match.start() - 1] in b"_abcdefghijklmnopqrstuvwxyz0123456789":
                continue
            string_rva = image.get_rva_from_offset(match.start())
            for ref in refs[string_rva]:
                if not in_ranges(ref, code) or image.get_data(ref - 1, 1) != b"\x68":
                    continue
                line = []
                for insn in instructions(image, ref - 1, 30):
                    line.append(f"{insn.address - image_base(image):08x} {insn.mnemonic} {insn.op_str}".rstrip())
                    if insn.mnemonic == "call":
                        operand = insn.operands[0]
                        imp = imports.get(operand.mem.disp) if operand.type == capstone.x86.X86_OP_MEM else None
                        hits.append({"label": name, "string_rva": hex(string_rva), "push_rva": hex(ref - 1),
                                     "call_rva": hex(insn.address - image_base(image)), "iat_symbol": imp,
                                     "instructions": line})
                        break
    return hits


def titan_report(path, image, refs):
    data = path.read_bytes()
    base = image_base(image)
    code = sections(image, 0x20000000)
    cli_rva = image.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress
    fixup_rva, fixup_size = struct.unpack("<II", image.get_data(cli_rva + 48, 8))
    if fixup_size % 8:
        raise ValueError("Invalid CLR vtable fixup directory")
    fixup_cells = set()
    for offset in range(0, fixup_size, 8):
        start, count, flags = struct.unpack("<IHH", image.get_data(fixup_rva + offset, 8))
        if flags & 1:  # COR_VTABLE_32BIT
            fixup_cells.update(range(start, start + count * 4, 4))

    interfaces = {}
    for label in ("MediaProtoXImpl@titancpp", "TitancppImpl@titancpp", "NervImpl@titancpp"):
        needle = (".?AV" + label + "@@\0").encode()
        tables = []
        for match in re.finditer(re.escape(needle), data):
            type_rva = image.get_rva_from_offset(match.start()) - 8
            for ref in refs[type_rva]:
                locator = ref - 12
                header = image.get_data(locator, 20)
                if len(header) != 20 or struct.unpack_from("<I", header)[0] != 0:
                    continue
                for pointer in refs[locator]:
                    table = pointer + 4
                    values = []
                    for slot in range(32):
                        cell = image.get_data(table + slot * 4, 4)
                        if len(cell) != 4:
                            break
                        target = struct.unpack("<I", cell)[0] - base
                        if not in_ranges(target, code):
                            break
                        entry = {"slot": slot, "target_rva": hex(target)}
                        thunk = image.get_data(target, 6)
                        if len(thunk) == 6 and thunk[:2] == b"\xff\x25":
                            fixup = struct.unpack_from("<I", thunk, 2)[0] - base
                            if fixup in fixup_cells:
                                token = struct.unpack("<I", image.get_data(fixup, 4))[0]
                                entry.update(fixup_rva=hex(fixup), method_token=hex(token))
                        values.append(entry)
                    if values:
                        tables.append({"type_descriptor_rva": hex(type_rva), "locator_rva": hex(locator),
                                       "vtable_rva": hex(table), "consecutive_code_pointers": values})
        interfaces[label] = tables
    imports = []
    for lib in image.DIRECTORY_ENTRY_IMPORT:
        if lib.dll.lower() == b"proxy.dll":
            for item in lib.imports:
                address = item.address - base
                imports.append({"symbol": item.name.decode(), "iat_rva": hex(address),
                                "indirect_jump_rvas": [hex(ref - 2) for ref in refs[address]
                                                       if image.get_data(ref - 2, 2) == b"\xff\x25"]})
    return {"clr_flags": hex(struct.unpack("<I", image.get_data(cli_rva + 16, 4))[0]),
            "vtable_fixup_directory_rva": hex(fixup_rva),
            "proxy_imports": imports, "msvc_rtti": interfaces}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", type=Path)
    args = parser.parse_args()
    paths = [args.install / name for name in ("libgonet.dll", "libtitancpp.dll", "proxy.dll")]
    go_path, titan_path, proxy_path = paths
    with read_image(go_path) as go, read_image(titan_path) as titan, read_image(proxy_path) as proxy:
        output = {
            "pe": {path.name: pe_summary(path, image) for path, image in zip(paths, (go, titan, proxy))},
            "gonet": go_report(go_path, go),
            "proxy_loader_xrefs": proxy_report(proxy_path, proxy, go, relocation_xrefs(proxy)),
            "titan": titan_report(titan_path, titan, relocation_xrefs(titan)),
        }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
