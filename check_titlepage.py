import sys
import zipfile
from pathlib import Path, PurePosixPath
from lxml import etree
import last_folder_helper

problems_only = False

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

def analyze_content(z, first_zip_path, book_title):
    indicators = {
        'has_svg': False,
        'has_cover_class': False,
        'has_cover_id': False,
        'has_cover_image_name': False,
        'has_title_image_name': False,
        'contains_title': False,
        'has_single_image': False,
        'has_center_align': False,
        'text_length': 0,
        'image_count': 0,
        'has_ebookmaker_cover_class': False,
        'has_minimal_text': False,
        'has_body_image': False
    }
    try:
        with z.open(first_zip_path) as f:
            content_tree = etree.parse(f, etree.XMLParser(recover=True))
            xhtml_ns = 'http://www.w3.org/1999/xhtml'
            svg_ns = 'http://www.w3.org/2000/svg'
            xlink_ns = 'http://www.w3.org/1999/xlink'
            svg_els = content_tree.findall(f'.//{{{xhtml_ns}}}svg')
            if not svg_els:
                svg_els = content_tree.findall(f'.//{{{svg_ns}}}svg')
            indicators['has_svg'] = len(svg_els) > 0
            all_els = content_tree.findall(f'.//*')
            for el in all_els:
                class_attr = el.get('class', '')
                id_attr = el.get('id', '')
                style_attr = el.get('style', '')
                if 'cover' in class_attr.lower():
                    indicators['has_cover_class'] = True
                    if 'ebookmaker' in class_attr.lower() or 'x-ebookmaker' in class_attr.lower():
                        indicators['has_ebookmaker_cover_class'] = True
                if 'cover' in id_attr.lower():
                    indicators['has_cover_id'] = True
                if 'text-align' in style_attr and 'center' in style_attr:
                    indicators['has_center_align'] = True
            text_nodes = [t.strip() for t in content_tree.itertext() if t.strip()]
            full_text = ' '.join(text_nodes)
            indicators['text_length'] = len(full_text)
            indicators['has_minimal_text'] = len(full_text) < 100
            if book_title and len(book_title) > 3:
                indicators['contains_title'] = book_title.lower() in full_text.lower()
            img_els = content_tree.findall(f'.//{{{xhtml_ns}}}img')
            svg_img_els = content_tree.findall(f'.//{{{svg_ns}}}image')
            svg_img_els += content_tree.findall(f'.//{{{xhtml_ns}}}svg//{{{svg_ns}}}image')
            image_els = img_els + svg_img_els
            indicators['image_count'] = len(image_els)
            indicators['has_single_image'] = len(image_els) == 1
            body_els = content_tree.findall(f'.//{{{xhtml_ns}}}body')
            if not body_els:
                body_els = [content_tree.getroot()]
            for body in body_els:
                body_children = list(body)
                if len(body_children) == 1:
                    child = body_children[0]
                    if child.tag.endswith('div') or child.tag.endswith('svg'):
                        grandchildren = list(child)
                        if len(grandchildren) == 1 and (grandchildren[0].tag.endswith('img') or grandchildren[0].tag.endswith('svg')):
                            indicators['has_body_image'] = True
            for el in image_els:
                src = el.get('src') or el.get(f'{{{xlink_ns}}}href')
                if src:
                    src_lower = src.lower()
                    if 'cover' in src_lower:
                        indicators['has_cover_image_name'] = True
                    if 'title' in src_lower:
                        indicators['has_title_image_name'] = True
    except Exception:
        pass
    return indicators

def classify_titlepage(basename_lower, indicators):
    reasons = []
    if 'titl' in basename_lower or 'cover' in basename_lower or 'wrap' in basename_lower:
        reasons.append('filename')
    if indicators['has_svg']:
        reasons.append('svg')
    if indicators['has_ebookmaker_cover_class']:
        reasons.append('ebookmaker-class')
    elif indicators['has_cover_class']:
        reasons.append('cover-class')
    if indicators['has_cover_id']:
        reasons.append('cover-id')
    if indicators['has_cover_image_name']:
        reasons.append('cover-img')
    if indicators['has_title_image_name']:
        reasons.append('title-img')
    if indicators['has_single_image'] and indicators['has_minimal_text']:
        reasons.append('single-img-minimal-text')
    elif indicators['has_single_image']:
        reasons.append('single-img')
    if indicators['has_body_image']:
        reasons.append('body-img-structure')
    if indicators['has_center_align'] and indicators['image_count'] > 0:
        reasons.append('centered-img')
    if indicators['contains_title'] and indicators['text_length'] < 200:
        reasons.append('title-text-short')
    if indicators['text_length'] < 50 and indicators['image_count'] > 0:
        reasons.append('very-minimal-text')
    return reasons

def main(epub_folder):
    p = Path(epub_folder).expanduser().resolve()
    if not p.is_dir():
        print(f"Folder not found: {p}")
        return
    epub_paths = sorted(p.rglob('*.epub'))
    if not epub_paths:
        print("No EPUB files found")
        return
    for epub_path in epub_paths:
        try:
            with zipfile.ZipFile(epub_path, 'r') as z:
                opf_path = find_opf_path(z)
                if opf_path is None:
                    print(f'{epub_path.name.removesuffix(".epub")[:30]:<30} SKIP: no OPF found')
                    continue
                manifest, opf_dir, root, ns = parse_opf(z, opf_path)
                first_zip_path, first_href = find_first_content_path(z, manifest, opf_dir, root, ns)
                if first_zip_path is None:
                    print(f'{epub_path.name.removesuffix(".epub")[:30]:<30} SKIP: no readable spine item')
                    continue
                basename = Path(first_href).name
                lower_basename = basename.lower()
                book_title = root.xpath('.//dc:title/text()', namespaces={'dc': 'http://purl.org/dc/elements/1.1/'})
                book_title = book_title[0].strip() if book_title else ""
                indicators = analyze_content(z, first_zip_path, book_title)
                reasons = classify_titlepage(lower_basename, indicators)
                if problems_only and reasons:
                    continue
                reason_str = '+'.join(reasons) if reasons else 'none'
                print(f'{epub_path.name.removesuffix(".epub")[:30]:<30} {reason_str}')
        except Exception as e:
            print(f'{epub_path.name.removesuffix(".epub")[:30]:<30} SKIP: processing error')

if __name__ == "__main__":
    try:
        default = last_folder_helper.get_last_folder()
        user_input = input(f'Input folder ({default}): ').strip()
        folder = user_input or default
        if not folder:
            folder = '.'
        last_folder_helper.save_last_folder(folder)
    except ImportError:
        if len(sys.argv) > 1:
            folder = sys.argv[1]
        else:
            folder = input('Input folder: ').strip() or '.'
    print()
    main(folder)

