import struct, json

with open('vrma/02_01.vrma', 'rb') as f:
    data = f.read()
pos = 12
while pos < len(data):
    clen, ctype = struct.unpack('<II', data[pos:pos+8])
    pos += 8
    if ctype == 0x4E4F534A:
        gltf = json.loads(data[pos:pos+clen].decode('utf-8'))
    elif ctype == 0x004E4942:
        break
    pos += clen

for i, bv in enumerate(gltf.get('bufferViews', [])):
    bo = bv.get('byteOffset', 0)
    bl = bv.get('byteLength', '?')
    print(f'bv[{i}]: byteOffset={bo}, byteLength={bl}')
