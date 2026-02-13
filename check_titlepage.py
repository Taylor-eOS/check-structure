from pathlib import Path, PurePosixPath
from lxml import etree
import zipfile
import last_folder_helper

print_yes = True

def find_opf_path(z):
    try:
        with z.open('META-INF/container.xml') as f:
            tree = etree.parse(f)
            rootfile = tree.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
            if rootfile is not None:
                return rootfile.get('full-path')
    except Exception:
        pass
    for name in z.namelist():
        if name.lower().endswith('.opf'):
            return name
    return None

def resolve_href(opf_dir, href):
    return (PurePosixPath(opf_dir) / PurePosixPath(href)).as_posix()

def parse_opf(z, opf_path):
    with z.open(opf_path) as f:
        parser = etree.XMLParser(recover=True)
        tree = etree.parse(f, parser)
        root = tree.getroot()
        opf_ns = None
        for ns in (root.nsmap or {}).values():
            if ns and 'opf' in ns:
                opf_ns = ns
                break
        if opf_ns is None:
            opf_ns = 'http://www.idpf.org/2007/opf'
        ns = {'opf': opf_ns}
        manifest = {}
        manifest_el = root.find('opf:manifest', ns)
        if manifest_el is not None:
            for item in manifest_el.findall('opf:item', ns):
                iid = item.get('id')
                href = item.get('href')
                media = item.get('media-type')
                props = item.get('properties') or ''
                if iid and href:
                    manifest[iid] = {'href': href, 'media-type': media, 'properties': props}
        opf_dir = PurePosixPath(opf_path).parent.as_posix()
        return manifest, opf_dir, root, ns

def find_first_content_path(z, manifest, opf_dir, root, ns):
    spine = root.find('opf:spine', ns)
    if spine is None:
        return None, None
    for itemref_el in spine.findall('opf:itemref', ns):
        if itemref_el.get('linear', 'yes') != 'no':
            idref = itemref_el.get('idref')
            if idref and idref in manifest:
                item = manifest[idref]
                mt = item['media-type']
                if mt in ('application/xhtml+xml', 'text/html'):
                    href = item['href']
                    zip_path = resolve_href(opf_dir, href)
                    return zip_path, href
    return None, None

def main(epub_folder):
    p = Path(epub_folder).expanduser().resolve()
    if not p.is_dir():
        print(f"Folder not found: {p}")
        return
    epub_paths = sorted(p.rglob('*.epub'))
    if not epub_paths:
        print("No EPUB files found")
        return
    yes_count = 0
    no_count = 0
    skip_count = 0
    for epub_path in epub_paths:
        try:
            with zipfile.ZipFile(epub_path, 'r') as z:
                opf_path = find_opf_path(z)
                if opf_path is None:
                    print(f'{epub_path.name.removesuffix(".epub")}: skipped (no OPF found)')
                    skip_count += 1
                    continue
                manifest, opf_dir, root, ns = parse_opf(z, opf_path)
                first_zip_path, first_href = find_first_content_path(z, manifest, opf_dir, root, ns)
                if first_zip_path is None:
                    print(f'{epub_path.name.removesuffix(".epub")}: skipped (no readable spine item)')
                    skip_count += 1
                    continue
                basename = Path(first_href).name
                lower_basename = basename.lower()
                book_title = root.xpath('.//dc:title/text()', namespaces={'dc': 'http://purl.org/dc/elements/1.1/'})
                book_title = book_title[0].strip() if book_title else ""
                has_dedicated = 'titlepage' in lower_basename or 'cover' in lower_basename
                contains_title = False
                has_svg = False
                has_cover_class = False
                has_cover_image_name = False
                if not has_dedicated:
                    try:
                        with z.open(first_zip_path) as f:
                            content_tree = etree.parse(f, etree.XMLParser(recover=True))
                            xhtml_ns = 'http://www.w3.org/1999/xhtml'
                            svg_ns = 'http://www.w3.org/2000/svg'
                            xlink_ns = 'http://www.w3.org/1999/xlink'
                            svg_els = content_tree.findall(f'.//{{{xhtml_ns}}}svg')
                            if not svg_els:
                                svg_els = content_tree.findall(f'.//{{{svg_ns}}}svg')
                            has_svg = len(svg_els) > 0
                            all_els = content_tree.findall(f'.//*')
                            for el in all_els:
                                class_attr = el.get('class', '')
                                id_attr = el.get('id', '')
                                if 'cover' in class_attr.lower() or 'cover' in id_attr.lower():
                                    has_cover_class = True
                                    break
                            text_nodes = [t.strip() for t in content_tree.itertext() if t.strip()]
                            full_text = ' '.join(text_nodes)
                            if book_title:
                                contains_title = book_title.lower() in full_text.lower()
                            img_els = content_tree.findall(f'.//{{{xhtml_ns}}}img')
                            svg_img_els = content_tree.findall(f'.//{{{svg_ns}}}image')
                            svg_img_els += content_tree.findall(f'.//{{{xhtml_ns}}}svg//{{{svg_ns}}}image')
                            image_els = img_els + svg_img_els
                            for el in image_els:
                                src = el.get('src') or el.get(f'{{{xlink_ns}}}href')
                                if src:
                                    src_lower = src.lower()
                                    if 'cover' in src_lower or 'title' in src_lower:
                                        has_cover_image_name = True
                                        break
                    except Exception:
                        pass
                if has_dedicated:
                    report = "yes, standard titlepage/cover filename"
                    yes_count += 1
                elif has_svg:
                    report = "yes, contains SVG element"
                    yes_count += 1
                elif has_cover_class:
                    report = "yes, has cover class/id attribute"
                    yes_count += 1
                elif has_cover_image_name:
                    report = "yes, image filename contains 'cover' or 'title'"
                    yes_count += 1
                elif contains_title:
                    report = "yes, contains book title in text"
                    yes_count += 1
                else:
                    report = "no clear indicators"
                    no_count += 1
                if not report[0] == 'y' or print_yes:
                    print(f'{epub_path.name.removesuffix(".epub")[:30]:<30}: {report}, {basename[:40].removesuffix(".xhtml").removesuffix(".html")}')
        except Exception:
            print(f'{epub_path.name.removesuffix(".epub")}: skipped (failed to process)')
            skip_count += 1
    print(f"\nProcessed {len(epub_paths)} files: {yes_count} have titlepage/equivalent as first, {no_count} do not, {skip_count} skipped")

if __name__ == "__main__":
    default = last_folder_helper.get_last_folder()
    user_input = input(f'Input folder ({default}): ').strip()
    folder = user_input or default
    if not folder:
        folder = '.'
    last_folder_helper.save_last_folder(folder)
    print()
    main(folder)
