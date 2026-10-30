#!/usr/bin/env python3
"""Build an offline code/assets update package; never include runtime data."""
import argparse
import io
import json
from pathlib import Path
import tarfile
import tempfile

import update_artel as updater


def build(source, output):
    source, output = source.resolve(), output.resolve()
    # Validate Python and reject source symlinks before packaging.
    with tempfile.TemporaryDirectory(prefix='artel-package-') as tmp:
        files = updater.plan(source, Path(tmp) / 'empty')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.tar.gz', delete=False) as f:
            temporary = Path(f.name)
        try:
            hashes = {}
            with tarfile.open(temporary, 'w:gz') as archive:
                for rel in files:
                    data = (source / rel).read_bytes()
                    hashes[rel.as_posix()] = updater.hashlib.sha256(data).hexdigest()
                    info = tarfile.TarInfo('artel-new/' + rel.as_posix())
                    info.size, info.mode = len(data), 0o644
                    archive.addfile(info, io.BytesIO(data))
                data = json.dumps({'format': 1, 'sha256': hashes}, ensure_ascii=False, indent=2).encode('utf-8')
                info = tarfile.TarInfo('artel-new/' + updater.RELEASE_MANIFEST)
                info.size, info.mode = len(data), 0o644
                archive.addfile(info, io.BytesIO(data))
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Пакет: {output}\nФайлов кода, документации и ассетов: {len(files)}. '
          'Рабочие конфиги, память, логи и настройки дашборда не включены; доступны только .sample-шаблоны.')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == '__main__':
    main()
