"""Read full official tar members, audit all rows, retain bounded uniform reservoirs."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import random
import re
import tarfile
from collections import Counter
from pathlib import Path

import numpy as np

from modules.my_comm.metrics import LABELS

OFFICIAL_ARCHIVES = {
    'ROSPaCe_reduced.tar.gz': (920868855, '63d2723577250282361b4c073b4912e5'),
    'ROSPaCe_reduced_noperiodicity.tar.gz': (697155970, '493995c64efe23e33047f6d820c61979'),
}


def shard_index(name):
    # Official reduced archive contains "rospace_reduced_11.csv " (space).
    # Preserve its original name in evidence, normalize only for recognition.
    name = name.rstrip()
    match = re.search(r'_(\d+)\.csv$', name)
    if not match:
        raise ValueError('Unexpected shard name: ' + name)
    return int(match.group(1))


def reservoir(reader, header, size, rng):
    """Scan every row. Sampling decisions never use label or feature values."""
    labels = Counter()
    reservoir_rows = []
    total = 0
    label_index = header.index('attack')
    for number, row in enumerate(reader, 1):
        if len(row) != len(header):
            raise ValueError(f'Row {number} has {len(row)} columns, expected {len(header)}')
        label = row[label_index]
        if label not in LABELS:
            raise ValueError('Unknown label: ' + repr(label))
        labels[label] += 1
        total += 1
        if len(reservoir_rows) < size:
            reservoir_rows.append((number, row))
        else:
            slot = rng.randrange(total)
            if slot < size:
                reservoir_rows[slot] = (number, row)
    return sorted(reservoir_rows), total, dict(labels)


def prepare(archive, output, feature_names, rows_per_shard=10000, seed=42):
    archive, output = Path(archive), Path(output)
    if archive.name.endswith('.partial'):
        raise ValueError('incomplete downloads cannot be used for training')
    if rows_per_shard < 100 or not feature_names or 'attack' in feature_names or 'timestamp' in feature_names:
        raise ValueError('invalid sampling/features')
    output.mkdir(parents=True, exist_ok=True)
    sha256, md5 = hashlib.sha256(), hashlib.md5()
    with archive.open('rb') as handle:
        for block in iter(lambda: handle.read(4*1024*1024), b''):
            sha256.update(block)
            md5.update(block)
    digest = sha256.hexdigest()
    official = OFFICIAL_ARCHIVES.get(archive.name)
    if official and (archive.stat().st_size, md5.hexdigest()) != official:
        raise ValueError('official archive size/MD5 mismatch')
    header = None
    # Official tar ordering is not numeric (_13 can precede _0). Locate the
    # genuine _0 header in a bounded preflight pass, never infer column order.
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if member.isfile() and member.name.rstrip().endswith('.csv') and shard_index(member.name) == 0:
                first = next(csv.reader(line.decode('utf-8') for line in tar.extractfile(member)))
                if 'attack' not in first or 'timestamp' not in first:
                    raise ValueError('_0 shard is missing the expected real header')
                header = first
                break
    if header is None:
        raise ValueError('archive is missing the _0 header shard')
    files = []
    seen_indices = set()
    # Each member is audited irrespective of archive order.
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if not member.isfile() or not member.name.rstrip().endswith('.csv'):
                continue
            index = shard_index(member.name)
            if index in seen_indices:
                raise ValueError('duplicate normalized shard index')
            seen_indices.add(index)
            raw = tar.extractfile(member)
            # Python 3.11 TextIOWrapper probes seekable() on ExFileObject;
            # streaming tar._Stream has no seekable method. Decode complete
            # lines instead, preserving CSV quoting and the bounded tar stream.
            reader = csv.reader(line.decode('utf-8') for line in raw)
            first = next(reader)
            has_header = 'attack' in first and 'timestamp' in first
            if has_header:
                if header is not None and first != header:
                    raise ValueError('header mismatch')
                header = first
            else:
                import itertools
                reader = itertools.chain([first], reader)
            if any(name not in header for name in feature_names):
                raise ValueError('missing configured feature in dataset')
            sampled, count, labels = reservoir(reader, header, rows_per_shard, random.Random(seed + index))
            columns = [header.index(name) for name in feature_names]
            x, y, row_numbers, times = [], [], [], []
            for row_number, row in sampled:
                vector = []
                for col in columns:
                    text = row[col]
                    if text in ('', 'nan', 'NaN', 'None'):
                        vector.append(np.nan)
                    else:
                        value = float(text)
                        if not np.isfinite(value):
                            raise ValueError('Infinite feature value')
                        vector.append(value)
                x.append(vector)
                y.append(row[header.index('attack')])
                row_numbers.append(row_number)
                times.append(row[header.index('timestamp')])
            destination = output / f'shard_{index}.npz'
            np.savez_compressed(destination, x=np.asarray(x, dtype=np.float64), labels=np.asarray(y),
                                rows=np.asarray(row_numbers), timestamps=np.asarray(times))
            files.append({'shard': index, 'archive_member': member.name, 'sample_file': destination.name,
                          'normalized_archive_member': member.name.rstrip(),
                          'full_rows': count, 'full_labels': labels, 'sample_rows': len(y), 'sample_labels': dict(Counter(y)),
                          'header': has_header, 'missing_fraction': np.isnan(x).mean(axis=0).tolist()})
            print(f'{member.name}: full={count} sampled={len(y)} labels={labels}', flush=True)
    if not files:
        raise ValueError('archive has no CSV members')
    manifest = {'source': 'official ROSPaCe archive' if official else 'caller-supplied archive (not verified as official)',
                'official_verification': 'SIZE_MD5_PASS' if official else 'NOT_OFFICIAL',
                'archive_md5': md5.hexdigest(), 'archive_sha256': digest, 'archive_name': archive.name,
                'feature_names': feature_names, 'original_nonlabel_fields': len(header)-1, 'model_feature_count': len(feature_names),
                'sampling': 'uniform reservoir across EVERY row in each shard; not first-N', 'seed': seed,
                'rows_per_shard': rows_per_shard, 'files': sorted(files, key=lambda f:f['shard']),
                'SESSION_INDEPENDENCE': 'UNVERIFIED', 'RUNTIME_MONITOR': 'NOT_READY'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
