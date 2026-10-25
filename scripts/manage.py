"""Small macOS operator CLI; dependencies are upstream packages, data stays in place."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'
DOMAIN = f'gui/{os.getuid()}'
SERVICES = {'memory': ('local.mcp-memory.shared', 'http://127.0.0.1:8000/api/health', 'start-central.sh'),
            'tasks': ('local.agent-tasks.dashboard', 'http://127.0.0.1:3422/health', 'run-tasks.sh')}

def envfile(name):
    values = {}
    for line in (ROOT / name).read_text().splitlines():
        tokens = shlex.split(line, comments=True)
        if tokens and tokens[0] == 'export': tokens.pop(0)
        if tokens:
            key, value = tokens[0].split('=', 1)
            values[key] = value
    return values

def run(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, **kwargs)

def ctl(*args, check=True):
    return run('launchctl', *args, check=check, capture_output=True, text=True)

def loaded(name):
    return ctl('print', DOMAIN + '/' + SERVICES[name][0], check=False).returncode == 0

def ready(name):
    try:
        with urllib.request.urlopen(SERVICES[name][1], timeout=2) as response:
            return response.status == 200
    except OSError: return False

def stop(name):
    if loaded(name): ctl('bootout', DOMAIN + '/' + SERVICES[name][0])
    for _ in range(100):
        if not ready(name):
            # Memory lock is held through model teardown, even after HTTP stops.
            if name == 'memory':
                with open(RUNTIME / 'server.lock', 'a+') as lock:
                    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        time.sleep(.2)
                        continue
            print(name + ': stopped')
            return
        time.sleep(.2)
    raise RuntimeError(name + ': shutdown timeout')

def start(name):
    label = SERVICES[name][0]
    if not loaded(name): ctl('bootstrap', DOMAIN, str(Path.home()/'Library/LaunchAgents'/f'{label}.plist'))
    else: ctl('kickstart', DOMAIN + '/' + label)
    for _ in range(180):
        if ready(name):
            print(name + ': ready')
            return
        time.sleep(.5)
    raise RuntimeError(name + ': startup timeout; see ./cli.sh logs ' + name)

def external_files():
    return [Path.home()/'.codex/config.toml', Path.home()/'.config/opencode/opencode.json',
            Path.home()/'.codex/AGENTS.md', Path.home()/'.config/opencode/AGENTS.md',
            *[Path.home()/'Library/LaunchAgents'/f'{v[0]}.plist' for v in SERVICES.values()]]

def backup():
    dest = ROOT/'backups'/datetime.now().strftime('snapshot-%Y%m%d-%H%M%S-%f')
    dest.mkdir(parents=True, mode=0o700)
    manifest = []
    for name, path in [('memory', envfile('memory.env')['MCP_MEMORY_SQLITE_PATH']),
                       ('tasks', envfile('tasks.env')['AGENT_TASKS_DB'])]:
        if not Path(path).exists():
            continue  # First installation has no database yet.
        with sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(dest/f'{name}.db') as dst:
            src.backup(dst)
            import sqlite_vec
            dst.enable_load_extension(True); sqlite_vec.load(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone() == ('ok',), name
        manifest.append({'database':path, 'backup':f'{name}.db'})
    files = external_files() + [RUNTIME/'api-key', ROOT/'memory.env', ROOT/'tasks.env', ROOT/'requirements.txt',
                               ROOT/'agent-tasks/package.json', ROOT/'agent-tasks/package-lock.json', ROOT/'model.sha256']
    for i, path in enumerate(files):
        target = dest/f'file-{i}'
        if path.exists():
            shutil.copy2(path,target);target.chmod(0o600)
            manifest.append({'path':str(path),'backup':target.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Backup:',dest)
    return dest

def install():
    backup()
    for name, (label, _, script) in SERVICES.items():
        stop(name)
        args = ['/bin/sh', str(ROOT/script)] if name == 'memory' else ['/bin/bash', str(ROOT/script), 'dashboard']
        config = {'Label':label,'ProgramArguments':args,'WorkingDirectory':str(ROOT/'runtime'),
                  'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ProcessType':'Background','Umask':0o077,
                  'StandardOutPath':str(RUNTIME/f'{name}.log'),'StandardErrorPath':str(RUNTIME/f'{name}.log')}
        path = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(plistlib.dumps(config));path.chmod(0o600)
        start(name)
    print('Installed. Configure client MCP connections as described in README.md.')

def status(names):
    failed = False
    for name in names:
        job = ctl('print',DOMAIN+'/'+SERVICES[name][0],check=False)
        health = ready(name)
        print(f'{name}: loaded={job.returncode == 0}, ready={health}')
        failed |= not health or job.returncode != 0
        for line in job.stdout.splitlines():
            if any(x in line for x in ('state =','pid =','last exit code =')):print('  '+line.strip())
    return 1 if failed else 0

def resources():
    lines = subprocess.check_output(['ps','-axo','pid=,ppid=,rss=,pcpu=,command='],text=True).splitlines()
    print(' PID   PPID   RSS(KiB) CPU% COMMAND')
    total = 0
    for line in lines:
        if str(ROOT) in line and any(x in line for x in ('memory_server.py','stdio.mjs','agent-tasks/dist/server.js')):
            print(line.strip());total += int(line.split()[2])
    print(f'Total RSS: {total/1024:.1f} MiB (shared pages may be counted more than once)')

def sync():
    lines = subprocess.check_output(['ps','-axo','command='],text=True)
    if any(str(ROOT/'agent-tasks/stdio.mjs') in line for line in lines.splitlines()):
        raise RuntimeError('Disconnect task MCP clients before sync; active stdio workers still use node_modules.')
    assert json.loads((ROOT/'agent-tasks/package.json').read_text())['dependencies']['agent-tasks']=='1.10.13'
    backup()
    running = [name for name in SERVICES if loaded(name)]
    for name in running: stop(name)
    # On failure leave services stopped: repair packages, then start explicitly.
    run('uv','pip','sync','--python',str(ROOT/'.venv/bin/python'),str(ROOT/'requirements.txt'))
    node = Path(envfile('tasks.env')['TASKS_NODE'])
    env = dict(os.environ, PATH=str(node.parent)+':'+os.environ.get('PATH',''))
    run(str(node.parent/'npm'),'ci','--prefix',str(ROOT/'agent-tasks'),env=env)
    for name in running: start(name)

def main():
    os.umask(0o077);RUNTIME.mkdir(mode=0o700,exist_ok=True)
    parser = argparse.ArgumentParser(description='Shared local MCP services')
    parser.add_argument('action',choices=['start','stop','restart','status','ram','dashboard','logs','backup','install','sync'])
    parser.add_argument('service',nargs='?',choices=['memory','tasks','all'],default='all')
    args=parser.parse_args();names=list(SERVICES) if args.service=='all' else [args.service]
    with open(RUNTIME/'control.lock','a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if args.action=='status':return status(names)
        if args.action=='ram':resources()
        elif args.action=='dashboard':
            for name in names: print(name+': '+SERVICES[name][1].split('/api/')[0].removesuffix('/health'))
            print('Memory login: existing API key in runtime/api-key')
        elif args.action=='logs':
            for name in names:
                path=RUNTIME/f'{name}.log';print(str(path))
                if path.exists():print('\n'.join(path.read_text(errors='replace').splitlines()[-40:]))
        elif args.action=='backup':backup()
        elif args.action=='install':install()
        elif args.action=='sync':sync()
        else:
            for name in names:
                if args.action in ('stop','restart'):stop(name)
                if args.action in ('start','restart'):start(name)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
