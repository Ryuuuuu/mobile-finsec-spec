"""Add public sample data to the locally authored S1 QA APK (never a real app)."""
import argparse
from pathlib import Path
import zipfile
from scan import MARKERS


def build(source, target):
    # Fixture generation only. The scanner independently enforces input budgets.
    with zipfile.ZipFile(source) as src:
        if sum(i.file_size for i in src.infolist()) > 1024 * 1024:
            raise ValueError('Expected small locally authored S1 QA APK')
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED) as dst:
            for info in src.infolist():
                dst.writestr(info.filename, src.read(info))
            dst.writestr('assets/public-qa-demo.txt', b'synthetic-only\n' + MARKERS['demo_token'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    build(args.source, args.target)
