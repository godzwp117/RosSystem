"""Download official archives with resumable verified byte ranges and full MD5.

Raw data is local-only under ignored data/. No archive is usable before final MD5.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ARTICLES={'reduced':25594860,'noperiodicity':25594854}


def download(dataset,directory,direct=False):
    directory=Path(directory).resolve()
    if not directory.is_relative_to((ROOT/'data').resolve()):
        raise ValueError('raw data must remain in ignored repository data/')
    directory.mkdir(parents=True,exist_ok=True)
    # Public-data connection fallback is scoped to this process. Never change
    # system proxy settings or disable certificate verification.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({})) if direct else urllib.request.build_opener()
    article=ARTICLES[dataset]
    with opener.open(f'https://api.figshare.com/v2/articles/{article}',timeout=30) as response:
        metadata=json.load(response)
    file=metadata['files'][0]
    target=directory/file['name']
    partial=target.with_suffix(target.suffix+'.partial')
    progress=target.with_suffix(target.suffix+'.progress.json')
    chunk=1024*1024
    expected={'file_id':file['id'],'size':file['size'],'md5':file['computed_md5']}
    if target.exists():
        with target.open('rb') as handle:
            if target.stat().st_size==expected['size'] and hashlib.file_digest(handle,'md5').hexdigest()==expected['md5']:
                print('Already verified:',target)
                return target
        raise ValueError('existing final archive fails verification; do not silently overwrite it')
    done={}
    if progress.exists():
        checkpoint=json.loads(progress.read_text(encoding='utf-8'))
        if checkpoint['metadata']!=expected or not partial.exists():
            raise ValueError('resume checkpoint does not match data file')
        done=checkpoint['chunks']
    (directory/(str(article)+'.metadata.json')).write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    with partial.open('r+b' if partial.exists() else 'w+b') as handle:
        for start in range(0,file['size'],chunk):
            end=min(start+chunk,file['size'])-1
            if str(start) in done:
                handle.seek(start)
                previous=handle.read(end-start+1)
                if hashlib.sha256(previous).hexdigest()==done[str(start)]:
                    continue
            # Figshare redirects use very short-lived S3 signatures. Never reuse
            # a cached redirect URL or a stable query string across retry attempts.
            for attempt in range(4):
                req=urllib.request.Request(file['download_url']+f'?member1-range={start}&fresh={time.time_ns()}',
                    headers={'Range':f'bytes={start}-{end}','Cache-Control':'no-cache'})
                try:
                    with opener.open(req,timeout=60) as response:
                        if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{file["size"]}':
                            raise ValueError('server did not return requested byte range')
                        data=response.read(end-start+1)
                        if len(data)!=end-start+1:
                            raise ValueError('incomplete download chunk')
                    break
                except (OSError,TimeoutError):
                    if attempt==3:
                        raise
                    time.sleep(attempt+1)
            handle.seek(start)
            handle.write(data)
            handle.flush()
            done[str(start)]=hashlib.sha256(data).hexdigest()
            checkpoint={'metadata':expected,'chunks':done}
            temporary=progress.with_suffix('.tmp')
            temporary.write_text(json.dumps(checkpoint),encoding='utf-8')
            temporary.replace(progress)
            print(f'{file["name"]}: {len(done)*chunk/1048576:.0f}/{file["size"]/1048576:.0f} MiB verified ranges',flush=True)
    with partial.open('rb') as handle:
        if partial.stat().st_size!=expected['size'] or hashlib.file_digest(handle,'md5').hexdigest()!=expected['md5']:
            raise ValueError('full size/MD5 mismatch; partial is not valid research data')
    partial.replace(target)
    print('MD5 verified:',target)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',choices=['reduced','noperiodicity','both'],default='both')
    parser.add_argument('--directory',type=Path,default=ROOT/'data/ROSPaCe_reduced')
    parser.add_argument('--direct',action='store_true',help='Process-local direct HTTPS fallback; TLS verification stays enabled')
    args=parser.parse_args()
    for name in ARTICLES if args.dataset=='both' else [args.dataset]:
        download(name,args.directory,args.direct)


if __name__=='__main__':
    main()
