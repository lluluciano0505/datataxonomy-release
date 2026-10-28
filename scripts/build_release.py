"""Export the current files to a clean source release without development history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    '.env.example', '.gitignore', 'LICENSE', 'README.md', 'config.example.yaml',
    'requirements.txt', 'main.py', 'install.bat', 'start_dashboard.bat',
    'stop_dashboard.bat', 'taxonomies/default.yaml', 'taxonomies/bijlmermeer_demo.yaml',
)
TREE_SUFFIXES = {
    'core': {'.py', '.json'},
    'server': {'.py'},
    'static': {'.html'},
    'scripts': {'.py'},
    'docs': {'.rst'},
    'tests': {'.py', '.txt'},
    'demo_data': {'.txt', '.docx', '.pdf', '.json', '.xlsx', '.csv', '.geojson',
                  '.png', '.dxf', '.svg', '.html', '.eml', '.ifc', '.md', '.yaml'},
}


def source_files(root: Path):
    """Only explicit release roots and file formats can enter the package."""
    files = {Path(name): root / name for name in ROOT_FILES}
    # A developer's currently active taxonomy is private local configuration.
    files[Path('taxonomy.yaml')] = root / 'taxonomies/default.yaml'
    for name, suffixes in TREE_SUFFIXES.items():
        for path in (root / name).rglob('*'):
            relative = path.relative_to(root)
            if (not path.is_file() or any(part.startswith('.') or part == '__pycache__'
                                          for part in relative.parts)
                    or path.suffix.lower() not in suffixes):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f'Release source must be a local regular file: {relative}')
            files[relative] = path
    return files


def build_release(destination: Path, root: Path = ROOT, version: str = '1.0.0'):
    root, destination = root.resolve(), destination.resolve()
    if destination == root or root.is_relative_to(destination):
        raise ValueError('Release destination must not contain the source checkout')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty release directory; existing files are preserved')
    files = source_files(root)
    for relative, source in files.items():
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Missing or unsafe release source: {relative}')
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for relative, source in sorted(files.items()):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {'name': 'DataTaxonomy', 'version': version, 'files': hashes}
    (destination / 'release-manifest.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='1.0.0')
    parser.add_argument('--zip', action='store_true', help='Also create a source ZIP beside the directory')
    args = parser.parse_args()
    manifest = build_release(args.output, version=args.version)
    if args.zip:
        destination = args.output.resolve()
        archive = destination.parent / (destination.name + '.zip')
        if archive.exists():
            raise ValueError('Archive already exists; choose another output path')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name in [*manifest['files'], 'release-manifest.json']:
                zf.write(destination / name, f'{destination.name}/{name}')
        print(f'Archive: {archive}')
    print(f'Release: {args.output.resolve()} ({len(manifest["files"])} files)')


if __name__ == '__main__':
    main()
