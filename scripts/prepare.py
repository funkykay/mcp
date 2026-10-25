"""Prepare local configuration and verify/download the exact ONNX model.

Existing configuration, keys and model files are never overwritten.
"""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shlex
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'paraphrase-multilingual-MiniLM-L12-v2'
REVISION = 'd4c06bf0d7680171ac30042a1387e1fdb7a90021'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-model', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    node = shutil.which('node')
    if not node:
        raise SystemExit('Install Node 24 and add it to PATH first.')
    for name in ('runtime', 'agent-tasks/data'):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    values = {'@HOME@': str(Path.home()), '@ROOT@': str(ROOT), '@NODE@': node}
    for name in ('memory.env', 'tasks.env'):
        target = ROOT / name
        if target.exists():
            continue
        lines = []
        for line in (ROOT / (name + '.example')).read_text().splitlines():
            if line.startswith('export '):
                key, value = shlex.split(line)[1].split('=', 1)
                for token, replacement in values.items():
                    value = value.replace(token, replacement)
                line = f'export {key}={shlex.quote(value)}'
            lines.append(line)
        with target.open('x') as stream:
            stream.write('\n'.join(lines) + '\n')
    key = ROOT / 'runtime/api-key'
    if not key.exists():
        with key.open('x') as stream:
            stream.write(secrets.token_hex(32) + '\n')
    from manage import envfile
    Path(envfile('memory.env')['MCP_MEMORY_SQLITE_PATH']).parent.mkdir(parents=True, exist_ok=True)
    model_dir = Path.home() / '.cache/mcp_memory/onnx_models' / MODEL
    for line in (ROOT / 'model.sha256').read_text().splitlines():
        expected, filename = line.split()
        path = model_dir / filename
        if not path.exists() and args.download_model:
            from huggingface_hub import hf_hub_download
            hf_hub_download(repo_id=f'onnx-community/{MODEL}-ONNX', revision=REVISION,
                            filename=filename, local_dir=model_dir)
        if not path.exists():
            raise SystemExit('Model missing: restore the cache or rerun with --download-model.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected:
            raise SystemExit(f'Model checksum mismatch: {filename}; existing file preserved.')
    print('Local configuration ready; all five model checksums verified.')


if __name__ == '__main__':
    main()
