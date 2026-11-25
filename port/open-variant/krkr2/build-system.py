#!/usr/bin/env python3
"""Build an Android 12 logical system image for this exact GammaOS baseline offline."""
import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

BASE_HASH = 'c1b02e6096a4a26d2d9f0e1935c43330636d64330f3ac563c2ea767645c2f17e'
PARTITION = 1318436864
FS_BYTES = 1297547264
DIRECTORY = 'system/etc/pixel2-krkr'
ODM = DIRECTORY+'/odm-lib'
ODM_LINK = ODM+'/modules'
ODM_LIB = ODM+'/libpixel2_krkr_v7.so'
ODM_LINK_TARGET = '/odm_dlkm/lib/modules'
BASE_SELINUX = 'u:object_r:system_file:s0'
ALLOWED = {
    'system/etc/init/pixel2-krkr.rc',
    'system/bin/pixel2-krkr-start',
    'system/lib/libpixel2_krkr_bootstrap.so',
}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(4<<20), b''):
            h.update(chunk)
    return h.hexdigest()

def run(*cmd, stdout=None):
    return subprocess.run([str(x) for x in cmd], check=True, stdout=stdout,
        env={**os.environ,'PATH':str(TOOLS)+':'+os.environ['PATH']})

def output(*cmd):
    return run(*cmd, stdout=subprocess.PIPE).stdout.decode()

def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')

def checked_payload(root, manifest):
    root=root.resolve(strict=True)
    raw=json.loads(manifest.read_text())
    require(isinstance(raw,list) and 0<len(raw)<=32,'declare 1–32 entries')
    result={}
    required_files=set()
    directories=set()
    total=0
    for original in raw:
        e=dict(original)
        name=e['path'];path=root/name;kind=e.get('type','file');mode=e['mode']
        require(name not in result and path.parent.resolve(strict=True)==path.parent,name)
        contexts={ODM:'u:object_r:vendor_file:s0',ODM_LINK:'u:object_r:vendor_file:s0',
                  ODM_LIB:'u:object_r:same_process_hal_file:s0','system/lib/libpixel2_krkr_bootstrap.so':'u:object_r:system_lib_file:s0'}
        require(e['selinux']==contexts.get(name,BASE_SELINUX),'unexpected label: '+name)
        common={'path','mode','selinux'}
        if 'type' in e:common.add('type')
        if kind=='directory':
            require(set(e)==common and name==ODM and mode=='0755',e)
            require(path.is_dir() and not path.is_symlink(),name)
            directories.add(name)
        elif kind=='symlink':
            require(set(e)==common|{'target'} and name==ODM_LINK and mode=='0644',e)
            require(e['target']==ODM_LINK_TARGET and path.is_symlink() and os.readlink(path)==ODM_LINK_TARGET,e)
            required_files.add(name)
        else:
            require(kind=='file' and set(e)==common|{'sha256'},e)
            require((name in ALLOWED or name==ODM_LIB or (name!=ODM and re.fullmatch(re.escape(DIRECTORY)+r'/[A-Za-z0-9][A-Za-z0-9._-]{0,85}',name))),name)
            require(mode in ('0444','0644','0755','0555') and (not name.endswith(('.rc','.so','.jar')) or mode in ('0644','0444')),e)
            require(re.fullmatch(r'[0-9a-f]{64}',e['sha256'] or ''),e)
            require(path.resolve(strict=True)==path and path.is_file(),'non-regular or aliased input: '+name)
            size=path.stat().st_size
            require(0<size<=28*(1<<20) and sha(path)==e['sha256'],'payload hash or size: '+name)
            total+=size;required_files.add(name)
        result[name]=(path,e)
    if any(name==ODM or name.startswith(ODM+'/') for name in result):
        require(ODM_LIB in result and ODM_LINK in result,'ODM mirror requires the driver AND original modules symlink')
        if ODM not in result:
            result[ODM]=(root/ODM,dict(type='directory',path=ODM,mode='0755',selinux='u:object_r:vendor_file:s0'))
        directories.add(ODM)
    if any(name.startswith(DIRECTORY+'/') for name in result):
        result[DIRECTORY]=(root/DIRECTORY,dict(type='directory',path=DIRECTORY,mode='0755',selinux=BASE_SELINUX))
        directories.add(DIRECTORY)
    actual_files={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_symlink() or not p.is_dir()}
    require(actual_files==required_files,'undeclared or missing input: '+str(actual_files^required_files))
    allowed_dirs={p.as_posix() for n in result for p in Path(n).parents}|directories
    actual_dirs={p.relative_to(root).as_posix() for p in root.rglob('*') if not p.is_symlink() and p.is_dir()}
    require(actual_dirs<=allowed_dirs,'undeclared subdirectories: '+str(actual_dirs-allowed_dirs))
    require(total<=36*(1<<20),'payload exceeds verified system budget')
    return result

def metadata(path, st):
    attrs=tuple((k,os.getxattr(path,k,follow_symlinks=False).hex()) for k in sorted(os.listxattr(path,follow_symlinks=False)))
    content=sha(path) if stat.S_ISREG(st.st_mode) else os.readlink(path) if stat.S_ISLNK(st.st_mode) else ''
    return (st.st_mode,st.st_uid,st.st_gid,st.st_rdev,attrs,content)

def tree(root):
    values={'.':metadata(root,root.lstat())}
    hardlinks={}
    for cur,dirs,files in os.walk(root):
        for name in dirs+files:
            path=Path(cur)/name
            key=path.relative_to(root).as_posix()
            st=path.lstat()
            values[key]=metadata(path,st)
            if stat.S_ISREG(st.st_mode) and st.st_nlink>1:
                hardlinks.setdefault(st.st_ino,[]).append(key)
    return values, sorted(sorted(paths) for paths in hardlinks.values())

@contextlib.contextmanager
def readonly(img, target):
    run('mount','-t','ext4','-o','loop,ro,noload',img,target)
    try:
        yield
    finally:
        run('umount',target)

def avb_info(img):
    return output(AVB,'info_image','--image',img)

def verify_fec(image, info, work):
    def field(name):
        found=re.search(r'(?m)^\s*'+re.escape(name)+r':[ \t]*(\d+)(?: bytes)?[ \t]*$',info)
        require(found is not None,'missing '+name)
        return int(found.group(1))
    offset=field('FEC offset');size=field('FEC size');roots=field('FEC num roots')
    require(FS_BYTES<offset<PARTITION and offset+size<=PARTITION and roots==2,'unexpected FEC geometry')
    with tempfile.TemporaryDirectory(prefix='fec-',dir=work) as tmp:
        temp=Path(tmp);prefix=temp/'data';parity=temp/'ecc'
        run('cp','--sparse=always','--reflink=auto',image,prefix)
        with prefix.open('r+b') as f:f.truncate(offset)
        run(TOOLS/'fec','--encode','--roots',str(roots),prefix,parity)
        with image.open('rb') as original,parity.open('rb') as encoded:
            original.seek(offset)
            remaining=size
            while remaining:
                take=min(remaining,1<<20)
                expected=encoded.read(take);stored=original.read(take)
                require(len(stored)==take and expected==stored,'FEC bytes differ')
                remaining-=take
    return size

def write_image(payload, dest):
    require(os.geteuid()==0,'start with wsl -u root -- unshare -m --propagation private')
    require(BASE.stat().st_size==PARTITION and sha(BASE)==BASE_HASH,'GammaOS baseline size or digest mismatch')
    dest.mkdir(exist_ok=False)
    orig_mount=dest/'origin-view'; orig_mount.mkdir()
    image_mount=dest/'candidate-view'; image_mount.mkdir()
    source_avb=avb_info(BASE)
    (dest/'baseline-avb.txt').write_text(source_avb)
    require(bool(re.search(r'Original image size:\s*'+str(FS_BYTES)+r'\s+bytes',source_avb)),source_avb[:500])
    run(AVB,'verify_image','--image',BASE,'--key',KEY)
    with readonly(BASE,orig_mount):
        source,links=tree(orig_mount)
        require(all(n not in source for n in (*payload,DIRECTORY)), 'baseline already includes an intended addition')
        for parent in ('system/etc','system/lib','system/bin','system/etc/init'):
            require(stat.S_ISDIR(source[parent][0]),parent)
    working=dest/'incomplete'; working.mkdir()
    partial=working/'system.img'
    run('cp','--sparse=always','--reflink=auto',BASE,partial)
    with partial.open('r+b') as f:
        f.truncate(FS_BYTES)
    cmds=[]
    for name,(path,e) in sorted(payload.items(),key=lambda item:(len(Path(item[0]).parts),item[0])):
        require(not any(c in str(path) for c in '"\\\r\n'),str(path))
        kind=e.get('type','file')
        if kind=='directory':
            cmds.append('mkdir /'+name)
        elif kind=='symlink':
            cmds.append(f"symlink /{name} {e['target']}")
        else:
            cmds.append(f'write "{path}" /{name}')
        file_types={'directory':stat.S_IFDIR,'symlink':stat.S_IFLNK,'file':stat.S_IFREG}
        mode=file_types[kind]|int(e['mode'],8)
        blob=dest/(e['selinux'].split(':')[2]+'.selinux')
        blob.write_bytes(e['selinux'].encode()+b'\0')
        cmds.extend([f'sif /{name} mode 0{mode:o}',f'sif /{name} uid 0',f'sif /{name} gid 0',f'ea_set -f {blob} /{name} security.selinux'])

    commands=dest/'changes.debugfs'
    commands.write_text('\n'.join(cmds)+'\n')
    with (dest/'debugfs.log').open('wb') as log:
        proc=subprocess.run(['/sbin/debugfs','-w','-f',str(commands),str(partial)],stdout=log,stderr=subprocess.STDOUT)
        require(proc.returncode==0,'debugfs failed')
    fsck=output('/sbin/e2fsck','-fn',partial)
    (dest/'e2fsck.txt').write_text(fsck)
    with readonly(partial,image_mount):
        built,actual_links=tree(image_mount)
    extras=set(built)-set(source)
    require(set(source)<=set(built) and all(source[k]==built[k] for k in source) and actual_links==links,
            'a baseline file, metadata, link or hard-link relationship changed')
    require(extras==set(payload),'unexpected added entries: '+str(extras^set(payload)))
    for name,(path,e) in payload.items():
        kind=e.get('type','file')
        attrs=(('security.selinux',(e['selinux'].encode()+b'\0').hex()),)
        content = e.get('target','') if kind=='symlink' else e.get('sha256','')
        expected=(file_types[kind]|int(e['mode'],8),0,0,0,attrs,content)
        require(built[name]==expected,('new inode content/type/target/mode/uid/gid/label mismatch',name,expected,built[name]))

    run(AVB,'add_hashtree_footer','--image',partial,'--partition_size',str(PARTITION),'--partition_name','system',
        '--algorithm','SHA256_RSA2048','--key',KEY,'--rollback_index','1699142400','--hash_algorithm','sha256',
        '--salt','0e3020406a069f08491e937bf0aff229030b2b1d8380f7ababc1c61586b9529e',
        '--prop','com.android.build.system.fingerprint:google/lineage_a64_bvN/phhgsi_a64_ab:12/SQ3A.220705.004/GKD20261118G4:userdebug/test-keys',
        '--prop','com.android.build.system.os_version:12','--prop','com.android.build.system.security_patch:2023-11-05')
    run(AVB,'verify_image','--image',partial,'--key',KEY)
    candidate_avb=avb_info(partial)
    (dest/'candidate-avb.txt').write_text(candidate_avb)
    def ignore_hash(s):return re.sub(r'Root Digest:[^\n]*','Root Digest: <measured>',s)
    require(partial.stat().st_size==PARTITION and ignore_hash(source_avb)==ignore_hash(candidate_avb),'changed AVB metadata or device geometry')
    fec_verified=verify_fec(partial,candidate_avb,working)
    candidate=dest/'system.img'
    partial.rename(candidate)
    result={'baseline':str(BASE),'baseline_sha256':BASE_HASH,'sha256':sha(candidate),'bytes':PARTITION,
            'existing_paths_verified':len(source),'hardlink_groups_verified':len(links),'added_directories':sorted(n for n,(p,e) in payload.items() if e.get('type')=='directory'),
            'added_files':[entry for _,entry in payload.values()],'avb':'SHA256_RSA2048, verified key and tree, same salt and rollback index','recomputed_fec_bytes':fec_verified,
            'ext4':'e2fsck -fn passed; all pre-existing file bytes, link targets, owners, modes, device numbers and xattrs match baseline'}
    save_json(dest/'verified.json',result)
    (dest/'SHA256SUMS').write_text(f"{result['sha256']}  system.img\n")
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--payload',required=True,type=Path)
    ap.add_argument('--manifest',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--baseline', type=Path, required=True, help='verified original logical system image')
    ap.add_argument('--gamma-source', type=Path, required=True, help='built GammaOSDistribution source tree')
    a=ap.parse_args()
    BASE = a.baseline.resolve(strict=True)
    GAMMA = a.gamma_source.resolve(strict=True)
    TOOLS = GAMMA / 'out-pixel2-gamma/host/linux-x86/bin'
    AVB = TOOLS / 'avbtool'
    KEY = GAMMA / 'external/avb/test/data/testkey_rsa2048.pem'
    folder=a.output.absolute()
    require(folder.parent.resolve()==folder.parent and re.fullmatch(r'/tmp/[A-Za-z0-9_./-]+',str(folder)) and '..' not in folder.parts,'output must be a new ordinary /tmp directory')
    write_image(checked_payload(a.payload,a.manifest),folder)
