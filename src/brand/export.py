from pathlib import Path
import struct
import subprocess

root = Path(__file__).resolve().parent
for theme in ('light', 'dark'):
    target = root / theme
    target.mkdir(exist_ok=True)
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        subprocess.run(['sips', '-z', str(size), str(size), str(root / f'tram-{theme}-master.png'), '--out', str(target / f'tram-{size}.png')], check=True, capture_output=True)
    chunks = []
    for tag, size in ((b'icp4',16),(b'icp5',32),(b'icp6',64),(b'ic07',128),(b'ic08',256),(b'ic09',512),(b'ic10',1024)):
        png = (target / f'tram-{size}.png').read_bytes()
        chunks.append(tag + struct.pack('>I',len(png)+8) + png)
    body = b''.join(chunks)
    (root / f'tram-{theme}.icns').write_bytes(b'icns' + struct.pack('>I',len(body)+8) + body)
    sizes = (16,32,48,64,128,256)
    entries, images = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        png = (target / f'tram-{size}.png').read_bytes()
        entries.append(struct.pack('<BBBBHHII',size % 256,size % 256,0,0,1,32,len(png),offset))
        images.append(png)
        offset += len(png)
    (root / f'tram-{theme}.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes)) + b''.join(entries+images))
print('Exported light/dark PNG sizes, ICNS, and ICO.')
