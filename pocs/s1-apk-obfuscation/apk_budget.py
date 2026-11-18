"""Finite configurable budgets and streaming APK snapshot/inventory."""
from dataclasses import asdict, dataclass, fields
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import time
import zipfile

MIB=1024*1024
CHUNK=128*1024
RESERVE=4*MIB


class ResourceError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    apk_mib:int=32
    entry_mib:int=8
    expanded_mib:int=64
    disk_mib:int=128
    min_free_mib:int=64
    tool_output_mib:int=4
    heap_mib:int=256
    total_seconds:int=120
    tool_seconds:int=30
    max_entries:int=1024
    max_dex_files:int=16
    compression_ratio:int=200
    central_directory_mib:int=4
    symbol_records:int=10000

    def validate(self):
        ranges={'apk_mib':(1,512),'entry_mib':(1,128),'expanded_mib':(1,1024),
                'disk_mib':(6,2048),'min_free_mib':(16,1024),'tool_output_mib':(1,16),
                'heap_mib':(64,1024),'total_seconds':(1,600),'tool_seconds':(1,120),
                'max_entries':(1,8192),'max_dex_files':(1,64),'compression_ratio':(1,200),
                'central_directory_mib':(1,16),'symbol_records':(1,20000)}
        for name,(low,high) in ranges.items():
            value=getattr(self,name)
            if type(value) is not int or not low<=value<=high:raise ResourceError('INVALID_BUDGET')
        if (self.entry_mib>self.expanded_mib or self.tool_seconds>self.total_seconds
                or self.disk_mib<self.apk_mib+self.tool_output_mib+4):
            raise ResourceError('INCONSISTENT_BUDGET')
        return self

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,dict) or set(value)-{f.name for f in fields(cls)}:
            raise ResourceError('INVALID_BUDGET_FIELDS')
        return cls(**value).validate()

    def snapshot(self):return asdict(self)


def time_guard(deadline):
    if time.monotonic()>deadline:raise ResourceError('ANALYSIS_TIMEOUT')


def used_bytes(folder):
    return sum(p.stat().st_size for p in Path(folder).iterdir() if p.is_file())


def storage_guard(folder,limits,extra=0,reserve=RESERVE):
    if used_bytes(folder)+extra>limits.disk_mib*MIB-reserve:raise ResourceError('DISK_BUDGET_LIMIT')
    if shutil.disk_usage(folder).free<limits.min_free_mib*MIB+extra:raise ResourceError('DISK_FREE_LIMIT')


def central_preflight(path,limits):
    # Bound metadata BEFORE ZipFile loads the central directory into Python memory.
    size=path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(max(0,size-65557));tail=stream.read(65557)
    offset=tail.rfind(b'PK\x05\x06')
    if offset<0 or len(tail)-offset<22:raise ResourceError('INVALID_ZIP_DIRECTORY')
    _,disk,start_disk,on_disk,total,cd_size,cd_offset,comment=struct.unpack_from('<4s4H2LH',tail,offset)
    if offset+22+comment!=len(tail):raise ResourceError('INVALID_ZIP_DIRECTORY')
    if disk or start_disk or on_disk!=total:raise ResourceError('UNSUPPORTED_MULTIDISK_ZIP')
    if total==65535 or cd_size==0xffffffff or cd_offset==0xffffffff:
        raise ResourceError('UNSUPPORTED_ZIP64')
    if total>limits.max_entries:raise ResourceError('ENTRY_LIMIT')
    if cd_size>limits.central_directory_mib*MIB:raise ResourceError('CENTRAL_DIRECTORY_LIMIT')
    if cd_offset+cd_size>size-len(tail)+offset:raise ResourceError('INVALID_ZIP_DIRECTORY')


def snapshot_inventory(source,folder,limits,deadline):
    source=Path(source);folder=Path(folder);snapshot=folder/'input.apk'
    if source.is_symlink():raise ResourceError('SYMLINK_INPUT')
    initial=source.stat()
    if initial.st_size>limits.apk_mib*MIB:raise ResourceError('INPUT_LIMIT')
    storage_guard(folder,limits,initial.st_size)
    hasher=hashlib.sha256();copied=0
    with source.open('rb') as src,snapshot.open('xb') as dest:
        while True:
            time_guard(deadline)
            chunk=src.read(CHUNK)
            if not chunk:break
            copied+=len(chunk)
            if copied>limits.apk_mib*MIB:raise ResourceError('INPUT_LIMIT')
            storage_guard(folder,limits,len(chunk))
            dest.write(chunk);hasher.update(chunk)
        final=os.fstat(src.fileno())
    if (initial.st_size,initial.st_mtime_ns)!=(final.st_size,final.st_mtime_ns):
        raise ResourceError('ARTIFACT_CHANGED_DURING_COPY')
    central_preflight(snapshot,limits)
    entries={};declared=0;expanded=0
    with zipfile.ZipFile(snapshot) as archive:
        infos=archive.infolist()
        if len(infos)>limits.max_entries:raise ResourceError('ENTRY_LIMIT')
        for info in infos:
            time_guard(deadline)
            name=info.filename
            if (info.orig_filename!=name or not name or name in entries or name.startswith('/')
                    or '\\' in name or ':' in name or '..' in PurePosixPath(name).parts
                    or info.flag_bits&1 or (info.external_attr>>16)&0o170000==0o120000):
                raise ResourceError('UNSAFE_ARCHIVE')
            declared+=info.file_size
            if (info.file_size>limits.entry_mib*MIB or declared>limits.expanded_mib*MIB
                    or info.file_size>limits.compression_ratio*max(info.compress_size,1)):
                raise ResourceError('EXPANSION_LIMIT')
            entry_hash=hashlib.sha256();entry_bytes=0
            with archive.open(info) as stream:
                while True:
                    time_guard(deadline)
                    chunk=stream.read(CHUNK)
                    if not chunk:break
                    entry_bytes+=len(chunk);expanded+=len(chunk)
                    if entry_bytes>limits.entry_mib*MIB or expanded>limits.expanded_mib*MIB:
                        raise ResourceError('EXPANSION_LIMIT')
                    entry_hash.update(chunk)
            if entry_bytes!=info.file_size:raise ResourceError('ENTRY_SIZE_MISMATCH')
            entries[name]=dict(bytes=entry_bytes,sha256=entry_hash.hexdigest())
    if 'AndroidManifest.xml' not in entries:raise ResourceError('MANIFEST_MISSING')
    info=dict(artifact_sha256=hasher.hexdigest(),bytes=copied,entries=len(entries),expanded_bytes=expanded,
              dex_entries=sum(bool(re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex',n)) for n in entries),
              native_entries=sum(n.startswith('lib/') and n.endswith('.so') for n in entries),
              resource_entries=sum(n.startswith('res/') for n in entries))
    return info,entries
