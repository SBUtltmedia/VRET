import struct, json

with open('vrma/test_transition.vrma', 'rb') as f:
    magic = struct.unpack('<I', f.read(4))[0]
    version = struct.unpack('<I', f.read(4))[0]
    length = struct.unpack('<I', f.read(4))[0]
    while f.tell() < length:
        cl = struct.unpack('<I', f.read(4))[0]
        ct = struct.unpack('<I', f.read(4))[0]
        cd = f.read(cl)
        if ct == 0x4E4F534A:
            j = json.loads(cd.decode('utf-8'))
            print(f'nodes: {len(j["nodes"])}')
            print(f'humanBones: {len(j["extensions"]["VRMC_vrm_animation"]["humanoid"]["humanBones"])}')
            print(f'channels: {len(j["animations"][0]["channels"])}')
            print(f'accessors: {len(j["accessors"])}')
            print(f'specVersion: {j["extensions"]["VRMC_vrm_animation"].get("specVersion")}')
            bones = j["extensions"]["VRMC_vrm_animation"]["humanoid"]["humanBones"]
            names = sorted(bones.keys())
            print(f'bone names: {len(names)}')
            # Check hips entry
            print(f'hips node: {bones["hips"]}')
            
            # Verify all animation channels point to valid nodes
            nodes = j["nodes"]
            anim = j["animations"][0]
            for ch in anim["channels"]:
                ni = ch["target"]["node"]
                assert 0 <= ni < len(nodes), f'Bad node index {ni}'
            print('All channel node indices valid')
            
            # Verify all humanBones point to valid nodes
            for name, info in bones.items():
                ni = info["node"]
                if not (0 <= ni < len(nodes)):
                    print(f'BAD: {name} -> node {ni} out of range')
            print('All humanBones node indices valid')
            break

# Now verify binary data reads correctly
with open('vrma/test_transition.vrma', 'rb') as f:
    f.seek(12)  # skip header
    while f.tell() < length:
        cl = struct.unpack('<I', f.read(4))[0]
        if cl == 0: break
        ct = struct.unpack('<I', f.read(4))[0]
        cd = f.read(cl)
        if ct == 0x004E4942:
            buf = cd
            buf_len = len(buf)
            # Read time accessor (first accessor)
            acc0 = j['accessors'][0]
            bv0 = j['bufferViews'][acc0['bufferView']]
            off = bv0.get('byteOffset', 0) + acc0.get('byteOffset', 0)
            cnt = acc0['count']
            times = struct.unpack_from('<' + 'f' * cnt, buf, off)
            print(f'Time values: [{times[0]:.4f} ... {times[-1]:.4f}], count={cnt}')
            
            # Read hips translation (last accessor, should be VEC3)
            last_acc = j['accessors'][-1]
            bv_last = j['bufferViews'][last_acc['bufferView']]
            off = bv_last.get('byteOffset', 0) + last_acc.get('byteOffset', 0)
            cnt = last_acc['count']
            print(f'Hips translation: type={last_acc["type"]}, count={cnt}')
            vals = struct.unpack_from('<' + 'f' * cnt * 3, buf, off)
            print(f'  first: ({vals[0]:.4f},{vals[1]:.4f},{vals[2]:.4f})')
            print(f'  last:  ({vals[-3]:.4f},{vals[-2]:.4f},{vals[-1]:.4f})')
            break
