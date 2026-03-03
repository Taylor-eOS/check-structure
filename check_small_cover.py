import zipfile
import struct
from pathlib import Path, PurePosixPath
import last_folder_helper
from complex_scan import find_opf_path
from check_cover_size import resolve_href

try:
    pixel_threshold = int(input('Pixel threshold (500): ').strip() or '500')
except ValueError:
    pixel_threshold = 500

def parse_opf(z, opf_path):
    from lxml import etree
    with z.open(opf_path) as f:
        tree = etree.parse(f, etree.XMLParser(recover=True))
        root = tree.getroot()
        opf_ns = next((ns for ns in (root.nsmap or {}).values() if ns and 'opf' in ns), 'http://www.idpf.org/2007/opf')
        ns = {'opf': opf_ns}
        manifest = {}
        manifest_el = root.find('opf:manifest', ns)
        if manifest_el is not None:
            for item in manifest_el.findall('opf:item', ns):
                iid, href, media = item.get('id'), item.get('href'), item.get('media-type')
                props = item.get('properties') or ''
                if iid and href:
                    manifest[iid] = {'href': href, 'media-type': media, 'properties': props}
        return manifest, PurePosixPath(opf_path).parent.as_posix(), root, ns

def find_cover_path(z, manifest, opf_dir, root, ns):
    version = root.get('version') or '2.0'
    if version.startswith('3'):
        for iid, item in manifest.items():
            if 'cover-image' in item.get('properties', '').split():
                return resolve_href(opf_dir, item['href'])
    meta = root.find('.//opf:meta[@name="cover"]', ns)
    if meta is not None:
        cid = meta.get('content')
        if cid and cid in manifest:
            return resolve_href(opf_dir, manifest[cid]['href'])
    candidates = [n for n in z.namelist() if PurePosixPath(n).suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif') and PurePosixPath(n).name.lower().startswith('cover.')]
    if candidates:
        return sorted(candidates, key=len)[0]
    return None

def get_image_dimensions(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        if len(data) >= 24:
            w, h = struct.unpack('>II', data[16:24])
            return w, h
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 8:
            if data[i] != 0xff:
                break
            marker = data[i+1]
            length = struct.unpack('>H', data[i+2:i+4])[0]
            if marker in (0xc0, 0xc1, 0xc2):
                h, w = struct.unpack('>HH', data[i+5:i+9])
                return w, h
            i += 2 + length
    return None, None

def main(folder):
    p = Path(folder).expanduser().resolve()
    if not p.is_dir():
        print(f"Folder not found: {p}")
        return
    epub_paths = sorted(p.rglob('*.epub'))
    if not epub_paths:
        print("No EPUB files found")
        return
    for epub_path in epub_paths:
        try:
            with zipfile.ZipFile(epub_path) as z:
                opf_path = find_opf_path(z)
                if opf_path is None:
                    continue
                manifest, opf_dir, root, ns = parse_opf(z, opf_path)
                cover_path = find_cover_path(z, manifest, opf_dir, root, ns)
                if cover_path is None:
                    continue
                with z.open(cover_path) as f:
                    data = f.read()
                w, h = get_image_dimensions(data)
                if w is None:
                    continue
                if max(w, h) < pixel_threshold:
                    print(f"{epub_path.name[:-5]}: {w}x{h}")
        except Exception:
            pass

if __name__ == "__main__":
    print(f"Current pixel threshold: {pixel_threshold}px on long side")
    default = last_folder_helper.get_last_folder()
    user_input = input(f'Input folder ({default}): ').strip()
    folder = user_input or default
    if not folder:
        folder = '.'
    last_folder_helper.save_last_folder(folder)
    print()
    main(folder)

