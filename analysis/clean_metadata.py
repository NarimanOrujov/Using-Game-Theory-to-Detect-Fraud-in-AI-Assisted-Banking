#!/usr/bin/env python3
"""Remove embedded document/image metadata while preserving visible content."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


def clean_pdf(path):
    import fitz

    with tempfile.NamedTemporaryFile(suffix='.pdf', dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
    try:
        with fitz.open(path) as doc:
            doc.set_metadata({})
            doc.del_xml_metadata()
            doc.xref_set_key(-1, 'Info', 'null')
            doc.xref_set_key(-1, 'ID', 'null')
            for xref in range(1, doc.xref_length()):
                if doc.xref_get_key(xref, 'Metadata')[0] != 'null':
                    doc.xref_set_key(xref, 'Metadata', 'null')
            # A full rewrite discards old metadata objects, unlike incremental edits.
            doc.save(temporary, garbage=4, deflate=True, no_new_id=True,
                     preserve_metadata=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def clean_png(path):
    data = path.read_bytes()
    signature = b'\x89PNG\r\n\x1a\n'
    if not data.startswith(signature):
        raise ValueError(f'Invalid PNG: {path}')
    chunks, offset = [signature], 8
    # Preserve pixel data, palette, and transparency; discard ancillary tags.
    keep = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS'}
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset+4])[0]
        kind = data[offset+4:offset+8]
        end = offset + length + 12
        if end > len(data):
            raise ValueError(f'Truncated PNG: {path}')
        if kind in keep:
            chunks.append(data[offset:end])
        offset = end
        if kind == b'IEND':
            break
    path.write_bytes(b''.join(chunks))


def clean_svg(path):
    text = path.read_text(encoding='utf-8')
    for tag in ('metadata', 'title', 'desc'):
        text = re.sub(rf'<{tag}\b[^>]*>.*?</{tag}\s*>', '', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'\s+aria-labelledby="[^"]*"', '', text)
    ET.fromstring(text)
    path.write_text(text, encoding='utf-8')


def clean_docx(path):
    with ZipFile(path) as source:
        files = {name: source.read(name) for name in source.namelist()
                 if not name.startswith('docProps/')}
    ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
    root = ET.fromstring(files['[Content_Types].xml'])
    for item in list(root):
        if item.get('PartName', '').startswith('/docProps/'):
            root.remove(item)
    ET.register_namespace('', ns)
    files['[Content_Types].xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    relns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    root = ET.fromstring(files['_rels/.rels'])
    for item in list(root):
        if item.get('Target', '').lstrip('/').startswith('docProps/'):
            root.remove(item)
    ET.register_namespace('', relns)
    files['_rels/.rels'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with ZipFile(path, 'w', ZIP_DEFLATED) as output:
        for name, data in files.items():
            # ZIP needs a date; use a fixed format minimum, not an edit time.
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.create_system = 0
            output.writestr(entry, data)


def clean_file(path):
    path = Path(path)
    cleaner = {'.pdf': clean_pdf, '.png': clean_png,
               '.svg': clean_svg, '.docx': clean_docx}.get(path.suffix.lower())
    if cleaner:
        cleaner(path)
    # Remove extended attributes when supported by the filesystem.
    if hasattr(os, 'listxattr'):
        for name in os.listxattr(path):
            os.removexattr(path, name)


def refresh_manifest(path):
    path = Path(path)
    recorded = json.loads(path.read_text())
    updated = {name: hashlib.sha256((path.parent/name).read_bytes()).hexdigest()
               for name in recorded}
    path.write_text(json.dumps(updated, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--manifest', type=Path,
                        help='Refresh an existing result manifest after cleaning.')
    args = parser.parse_args()
    for target in args.paths:
        files = sorted(target.rglob('*')) if target.is_dir() else [target]
        for path in files:
            if path.is_file():
                clean_file(path)
    if args.manifest:
        refresh_manifest(args.manifest)
    print('Embedded metadata removed.')
