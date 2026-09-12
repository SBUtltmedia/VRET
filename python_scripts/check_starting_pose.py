import struct, json, os, math

def read_glb_json(path):
    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        assert magic == 0x46546C67
        struct.unpack('<I', f.read(4))[0]  # version
        length = struct.unpack('<I', f.read(4))[0]
        while f.tell() < length:
            chunk_len = struct.unpack('<I', f.read(4))[0]
            chunk_type = struct.unpack('<I', f.read(4))[0]
            chunk_data = f.read(chunk_len)
            if chunk_type == 0x4E4F534A:
                return json.loads(chunk_data.decode('utf-8'))
    return None

clips = [
    '02_01.vrma', '02_03.vrma', '02_04.vrma',
    '05_01.vrma', '07_01.vrma', '07_12.vrma',
    '08_05.vrma', '08_07.vrma', '09_01.vrma',
    '104_02.vrma', '104_31.vrma', '104_44.vrma',
    '18_08.vrma', '18_10.vrma', '13_27.vrma',
    '111_22.vrma', '111_28.vrma',
]

print('=== Starting Pose per VRMA (frame 0) ===')
print('%-20s %6s %-24s %8s %8s %8s   %s' % ('Clip', 'Frames', 'Hips.position', 'Hips.rotX', 'Hips.rotY', 'Hips.rotZ', 'Hips.posY'))
print('-' * 90)

for clip in clips:
    path = os.path.join('D:/VRE/vrma', clip)
    if not os.path.exists(path):
        print('%-20s  MISSING' % clip)
        continue
    data = read_glb_json(path)
    if not data:
        print('%-20s  PARSE ERROR' % clip)
        continue
    acc = data['accessors']
    frames = acc[0]['count']

    # Read binary buffer
    with open(path, 'rb') as f:
        f.seek(12)
        buf = None
        while f.tell() < os.path.getsize(path):
            cl = struct.unpack('<I', f.read(4))[0]
            ct = struct.unpack('<I', f.read(4))[0]
            cd = f.read(cl)
            if ct == 0x004E4942:
                buf = cd
                break
    if not buf:
        print('%-20s  NO BIN' % clip)
        continue

    # Hips position: acc[1] (VEC3)
    pos_acc = acc[1]
    bv = data['bufferViews'][pos_acc['bufferView']]
    off = bv.get('byteOffset', 0) + pos_acc.get('byteOffset', 0)
    px, py, pz = struct.unpack_from('<3f', buf, off)

    # Hips rotation: acc[3] (VEC4) -> Euler
    rot_acc = acc[3]
    bv_r = data['bufferViews'][rot_acc['bufferView']]
    off_r = bv_r.get('byteOffset', 0) + rot_acc.get('byteOffset', 0)
    qx, qy, qz, qw = struct.unpack_from('<4f', buf, off_r)

    # Quaternion to Euler XYZ
    sinr_cosp = 2 * (qw * qx + qy * qz)
    cosr_cosp = 1 - 2 * (qx * qx + qy * qy)
    rx = math.atan2(sinr_cosp, cosr_cosp) * 180 / math.pi

    sinp = 2 * (qw * qy - qz * qx)
    if abs(sinp) >= 1:
        ry = math.copysign(90, sinp)
    else:
        ry = math.asin(sinp) * 180 / math.pi

    siny_cosp = 2 * (qw * qz + qx * qy)
    cosy_cosp = 1 - 2 * (qy * qy + qz * qz)
    rz = math.atan2(siny_cosp, cosy_cosp) * 180 / math.pi

    # Get first time value
    bv_t = data['bufferViews'][acc[0]['bufferView']]
    off_t = bv_t.get('byteOffset', 0) + acc[0].get('byteOffset', 0)
    t0 = struct.unpack_from('<f', buf, off_t)[0]

    # Get last frame Hips position
    pos_last_off = off + (frames - 1) * 12
    px1, py1, pz1 = struct.unpack_from('<3f', buf, pos_last_off)

    print('%-20s %6d  (%7.3f, %7.3f, %7.3f)  t0=%6.3f  last=(%7.3f, %7.3f, %7.3f)  dY=%+.3f' % (
        clip, frames, px, py, pz, t0, px1, py1, pz1, py1-py))
