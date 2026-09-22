#!/usr/bin/env python3
"""Read bounded Go heap pprof samples without a Go installation.

Schema: https://github.com/google/pprof/blob/main/proto/profile.proto
Reports inuse_space function attribution only, not process physical footprint.
"""
import argparse
from collections import Counter
import gzip
import io
import json
import zlib
from pathlib import Path

MAX_PROFILE_BYTES = 64 * 1024**2


def varint(stream):
    value = 0
    for offset in range(10):
        byte = stream.read(1)
        if not byte:
            raise ValueError('Truncated protobuf integer')
        number = byte[0]
        if offset == 9 and number > 1:
            raise ValueError('Protobuf integer exceeds 64 bits')
        value |= (number & 127) << (offset * 7)
        if not number & 128:
            return value
    raise ValueError('Oversized protobuf integer')


def fields(data):
    if not isinstance(data, bytes):
        raise ValueError('Expected a protobuf message')
    stream = io.BytesIO(data)
    while stream.tell() < len(data):
        tag = varint(stream)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError('Invalid protobuf field number')
        if wire == 0:
            yield number, varint(stream)
            continue
        if wire == 2:
            size = varint(stream)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
        else:
            raise ValueError('Unsupported protobuf wire type')
        if size > len(data) - stream.tell():
            raise ValueError('Truncated protobuf field')
        yield number, stream.read(size)


def integers(value):
    if isinstance(value, int):
        return [value]
    stream = io.BytesIO(value)
    result = []
    while stream.tell() < len(value):
        result.append(varint(stream))
    return result


def summarize(data, count=12):
    if len(data) > MAX_PROFILE_BYTES:
        raise ValueError('Heap profile exceeds size limit')
    strings, types, functions, locations = [], [], {}, {}
    for number, value in fields(data):
        if number == 1:
            types.append(dict(fields(value)))
        elif number == 5:
            record = dict(fields(value))
            identity = record.get(1, 0)
            if not isinstance(identity, int) or not identity or identity in functions:
                raise ValueError('Invalid or duplicate function ID')
            functions[identity] = record.get(2, 0)
        elif number == 4:
            record = list(fields(value))
            identity = dict(record).get(1, 0)
            if not isinstance(identity, int) or not identity or identity in locations:
                raise ValueError('Invalid or duplicate location ID')
            locations[identity] = [dict(fields(v)).get(1, 0) for n, v in record if n == 4]
        elif number == 6:
            if not isinstance(value, bytes):
                raise ValueError('Expected a profile string')
            strings.append(value.decode('utf-8'))
        elif number in (7, 8) and value:
            raise ValueError('Frame filtering is outside this heap diagnostic')
    if not strings or strings[0] != '':
        raise ValueError('Invalid profile string table')

    def string(index):
        if not isinstance(index, int) or not 0 <= index < len(strings):
            raise ValueError('Invalid profile string index')
        return strings[index]

    matches = [i for i, t in enumerate(types)
               if (string(t.get(1, 0)), string(t.get(2, 0))) == ('inuse_space', 'bytes')]
    if len(matches) != 1:
        raise ValueError('Requires exactly one inuse_space/bytes sample type')
    index = matches[0]
    names = {identity: string(name) or '<unnamed>' for identity, name in functions.items()}
    flat, cumulative = Counter(), Counter()
    total = samples = 0
    for number, value in fields(data):
        if number != 2:
            continue
        ids, values = [], []
        for n, v in fields(value):
            if n == 1:
                ids.extend(integers(v))
            elif n == 2:
                values.extend(integers(v))
        if len(values) != len(types):
            raise ValueError('Sample value count differs from sample types')
        size = values[index]
        if size >= 1 << 63:
            raise ValueError('Negative heap sample; differential profiles unsupported')
        stack = []
        for identity in ids:
            if identity not in locations:
                raise ValueError('Sample references missing location')
            for function in locations[identity]:
                if function not in names:
                    raise ValueError('Location references missing function')
                stack.append(names[function])
            if not locations[identity]:
                stack.append('<unsymbolized>')
        if not stack:
            stack = ['<unknown>']
        total += size
        samples += 1
        flat[stack[0]] += size
        for name in set(stack):
            cumulative[name] += size  # Count recursive/inlined repeats only once.

    def top(counter):
        return [{'function': name[:240], 'bytes': size, 'mib': round(size / 1024**2, 3)}
                for name, size in counter.most_common(count) if size]
    return {'sample_type': 'inuse_space', 'unit': 'bytes', 'samples': samples,
            'sampled_total_bytes': total, 'sampled_total_mib': round(total / 1024**2, 3),
            'flat': top(flat), 'cumulative': top(cumulative),
            'scope': 'Sampled Go heap attribution; not physical footprint or an exact peak measurement.'}


def read_profile(path):
    with gzip.open(path, 'rb') as stream:
        data = stream.read(MAX_PROFILE_BYTES + 1)
    return summarize(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    profiles = sorted(args.directory.glob('siso-memory.*.pprof'))
    reports = []
    for path in reversed(profiles):
        try:
            reports.append({'profile': path.name, **read_profile(path)})
        except (ValueError, OSError, EOFError, zlib.error) as error:
            print(json.dumps({'profile': path.name, 'error': str(error)}))
            continue  # A killed process may leave its last rolling sample incomplete.
        if len(reports) == 2:
            break
    if not reports:
        raise SystemExit('No complete heap profile could be summarized')
    for report in reversed(reports):
        print(json.dumps(report))


if __name__ == '__main__':
    main()
