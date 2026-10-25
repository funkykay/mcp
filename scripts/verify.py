"""Read-only live checks; --isolated writes only to temporary SQLite copies.

--native additionally uses installed Codex/OpenCode (may incur model costs).
Memory is stopped during isolated tests, then restored, to keep one model loaded.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
import sqlite_vec
import manage

ROOT=manage.ROOT
KEY=(ROOT/'runtime/api-key').read_text().strip()
MEMDB=Path(manage.envfile('memory.env')['MCP_MEMORY_SQLITE_PATH'])
TASKDB=Path(manage.envfile('tasks.env')['AGENT_TASKS_DB'])
NODE=manage.envfile('tasks.env')['TASKS_NODE']


def fingerprint(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.enable_load_extension(True);sqlite_vec.load(db)
        # Exclude access counters: legitimate reads may update those.
        memories=db.execute('select id,content_hash,content,tags,metadata from memories order by id').fetchall()
        vectors=db.execute('select rowid,content_embedding from memory_embeddings order by rowid').fetchall()
        return len(memories),len(vectors),hashlib.sha256(repr((memories,vectors)).encode()).hexdigest()


def fetch(path,port=8000,key=KEY,headers=None,method=None,data=None):
    hdr={'Authorization':'Bearer '+key} if key else {}
    hdr.update(headers or {})
    request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers=hdr,method=method,data=data)
    with urllib.request.urlopen(request,timeout=15) as r:return r.read()


def denied(path,code,**kwargs):
    try:fetch(path,**kwargs)
    except urllib.error.HTTPError as e:assert e.code==code,(path,e.code,code)
    else:raise AssertionError('Request accepted: '+path)


async def memory_session(stack,port,key,name):
    client=await stack.enter_async_context(httpx.AsyncClient(headers={'Authorization':'Bearer '+key,'X-Agent-ID':name},timeout=60))
    r,w,_=await stack.enter_async_context(streamable_http_client(f'http://127.0.0.1:{port}/mcp',http_client=client))
    session=await stack.enter_async_context(ClientSession(r,w));init=await session.initialize()
    assert len((await session.list_tools()).tools)==26
    return session


async def task_session(stack,env):
    r,w=await stack.enter_async_context(stdio_client(StdioServerParameters(command=NODE,args=[str(ROOT/'agent-tasks/stdio.mjs')],env=env)))
    s=await stack.enter_async_context(ClientSession(r,w));await s.initialize()
    assert len((await s.list_tools()).tools)==8
    return s


async def call(session,name,args):
    r=await session.call_tool(name,args);assert not r.isError,(name,r)
    text='\n'.join(x.text for x in r.content if hasattr(x,'text'))
    return text


async def live_sessions():
    async def one(n):
        async with AsyncExitStack() as stack:
            s=await memory_session(stack,8000,KEY,f'verify-{n}')
            return await call(s,'memory_list',{'page_size':100})
    results=await asyncio.gather(*(one(n) for n in range(6)))
    assert len(set(results))==1,'Agent identity unexpectedly filters shared memories'
    async with AsyncExitStack() as stack:
        s=await task_session(stack,dict(os.environ,**manage.envfile('tasks.env')))
        tasks=json.loads(await call(s,'task_list',{'project':'mcp'}))
        for task in tasks:
            rest=json.loads(fetch('/api/tasks/'+str(task['id']),port=3422,key=None))
            assert rest['title']==task['title'] and rest['id']==task['id']
    print('PASS: 6 concurrent Memory sessions, 26 tools; Tasks 8 tools, MCP/REST data match',flush=True)


def live():
    before=fingerprint(MEMDB)
    asyncio.run(live_sessions())
    for port in (8000,3422):assert b'<html' in fetch('/',port=port,key=None).lower()
    denied('/api/memories',401,key=None)
    denied('/mcp',401,key=None,method='POST',data=b'{}')
    denied('/mcp',401,key='wrong',method='POST',data=b'{}')
    for port in (8000,3422):
        denied('/',403,port=port,headers={'Origin':'https://evil.invalid'})
        denied('/',403,port=port,headers={'Host':'evil.invalid'})
    stats=json.loads(fetch('/api/memory-stats'));model=json.loads(fetch('/api/health/model'))
    assert stats['model_cache_count']==1,stats
    assert model['embedding_model']=='paraphrase-multilingual-MiniLM-L12-v2',model
    assert fingerprint(MEMDB)==before
    for name in manage.SERVICES:
        import plistlib
        p=Path.home()/'Library/LaunchAgents'/f'{manage.SERVICES[name][0]}.plist'
        c=plistlib.loads(p.read_bytes());assert c['RunAtLoad'] and c['KeepAlive']
        assert manage.loaded(name) and manage.ready(name)
    print('PASS: dashboards, authentication, Host/Origin, one cached model, login configuration; original memory/embeddings unchanged',flush=True)
    print('Memory baseline:',before,flush=True)
    manage.resources()


async def roundtrip(folder,env):
    async with AsyncExitStack() as stack:
        a=await memory_session(stack,18765,'test-secret-only','codex-test')
        b=await memory_session(stack,18765,'test-secret-only','opencode-test')
        for writer,reader,text,query in [(a,b,'Der violette Pinguin wohnt in Berlin.','The purple penguin lives in Berlin.'),
                                       (b,a,'The green telescope is in London.','Das grüne Teleskop befindet sich in London.')]:
            await call(writer,'memory_store',{'content':text,'metadata':{'tags':['isolated-verification']}})
            assert text in await call(reader,'memory_list',{'tags':['isolated-verification']})
            assert text in await call(reader,'memory_search',{'query':query,'mode':'semantic','limit':3})
        a=await task_session(stack,env);b=await task_session(stack,env)
        await call(a,'task_config',{'action':'session','id':'test-codex','name':'test-codex'})
        task=json.loads(await call(a,'task_create',{'title':'Isolated shared task','project':'test'}))
        task_id=task['id']
        assert 'Isolated shared task' in await call(b,'task_get',{'task_id':task_id})
        await call(b,'task_update',{'task_id':task_id,'title':'Updated by second session'})
        assert 'Updated by second session' in await call(a,'task_get',{'task_id':task_id})
        assert json.loads(fetch('/api/tasks/'+str(task_id),port=13422,key=None))['title']=='Updated by second session'
    print('PASS: isolated bidirectional writes, DE↔EN semantic search, task create/read/update, dashboard data',flush=True)


def native(folder,env):
    # Only isolated endpoints are configured. No production MCP tools in either run.
    url='http://127.0.0.1:18765/mcp'
    codex=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','-C',str(folder),'--json',
           '-c',f'mcp_servers.shared-memory.url="{url}"',
           '-c','mcp_servers.shared-memory.http_headers={Authorization="Bearer test-secret-only", "X-Agent-ID"="codex-native"}',
           '-c','mcp_servers.agent-tasks.command='+json.dumps(NODE),
           '-c','mcp_servers.agent-tasks.args='+json.dumps([str(ROOT/'agent-tasks/stdio.mjs')]),
           '-c','mcp_servers.agent-tasks.env={AGENT_TASKS_DB='+json.dumps(env['AGENT_TASKS_DB'])+'}']
    for tool in ['memory_store','memory_list']:
        codex+=['-c',f'mcp_servers.shared-memory.tools.{tool}.approval_mode="approve"']
    for tool in ['task_create','task_get','task_list']:
        codex+=['-c',f'mcp_servers.agent-tasks.tools.{tool}.approval_mode="approve"']
    def execute(name,command,client_env):
        target=ROOT/'runtime'/f'verify-{name}.jsonl'
        with target.open('w') as log:
            p=subprocess.Popen(command,cwd=folder,env=client_env,stdout=log,stderr=log,start_new_session=True)
            try:code=p.wait(timeout=240)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=20);raise
        assert code==0,(name,code,target)
        print('Native client finished:',name,flush=True)
        return target.read_text()
    text=execute('codex-create',codex+['Explicit isolated integration test, not project work. Use only MCP tools. Call shared-memory memory_store with content "native codex verification marker" and metadata tags ["native-verification"]. Then call agent-tasks task_create with title "native codex verification task", project "native-test". Return results; stop. No other tasks, files or shell.'],os.environ.copy())
    def successful(log,tool):
        for line in log.splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            i=e.get('item',{})
            if i.get('type')=='mcp_tool_call' and i.get('tool')==tool and i.get('status')=='completed' and i.get('result') and not i.get('error'):return True
        return False
    assert successful(text,'memory_store') and successful(text,'task_create'),text[-1500:]
    with sqlite3.connect(env['AGENT_TASKS_DB']) as db:
        task_id=db.execute('select id from tasks where title=?',('native codex verification task',)).fetchone()[0]
    config={'mcp':{'servers':{'shared-memory':{'type':'remote','url':url,'oauth':False,'headers':{'Authorization':'Bearer test-secret-only','X-Agent-ID':'opencode-native'}},
                            'agent-tasks':{'type':'local','command':[NODE,str(ROOT/'agent-tasks/stdio.mjs')],'environment':{'AGENT_TASKS_DB':env['AGENT_TASKS_DB']}}}}}
    client_env=dict(os.environ,OPENCODE_CONFIG_CONTENT=json.dumps(config),OPENCODE_CONFIG_PROJECT_DISABLE='true')
    execute('opencode-update',['opencode','run','--standalone','--format','json',
        'Explicit isolated integration test. Use only the two MCPs through execute, discover tools if necessary. '
        'Call shared-memory memory_list({tags:["native-verification"]}) and report the Codex marker. '
        'Call memory_store({content:"native opencode verification marker",metadata:{tags:["native-verification"]}}). '
        f'Call agent-tasks task_get({{task_id:{task_id}}}), then task_update({{task_id:{task_id},title:"native task updated by opencode"}}). '
        'Report all results; stop. No files, shell, additional planning tasks or other tools.'],client_env)
    text=execute('codex-readback',codex+[f'Isolated integration test. Only call shared-memory memory_list with tags ["native-verification"] and agent-tasks task_get with task_id {task_id}. Report both native markers and the updated task title. Stop; no shell/files.'],os.environ.copy())
    assert successful(text,'memory_list') and successful(text,'task_get')
    assert 'native opencode verification marker' in text and 'native task updated by opencode' in text
    with sqlite3.connect(folder/'memory.db') as db:assert db.execute('select count(*) from memories where content=?',('native opencode verification marker',)).fetchone()[0]==1
    assert json.loads(fetch(f'/api/tasks/{task_id}',port=13422,key=None))['title']=='native task updated by opencode'
    print('PASS: actual Codex→OpenCode→Codex, both MCPs, isolated shared data',flush=True)


def isolated(use_native):
    before=fingerprint(MEMDB)
    restart=manage.loaded('memory')
    manage.stop('memory')
    try:
        with tempfile.TemporaryDirectory(prefix='mcp-verify-') as tmp:
            folder=Path(tmp)
            for source,name in [(MEMDB,'memory.db'),(TASKDB,'tasks.db')]:
                with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(folder/name) as dest:src.backup(dest)
            env=dict(os.environ,**manage.envfile('memory.env'))
            env.update(MCP_MEMORY_SQLITE_PATH=str(folder/'memory.db'),MCP_MEMORY_BASE_DIR=str(folder/'data'),MCP_API_KEY='test-secret-only',
                       MCP_ALLOW_ANONYMOUS_ACCESS='false',MCP_OAUTH_ENABLED='false',MCP_MDNS_ENABLED='false',MCP_BACKUP_ENABLED='false',
                       MCP_MEMORY_ONNX_ALLOW_DOWNLOAD='0',MEMORY_PORT='18765',MEMORY_LOCK_PATH=str(ROOT/'runtime/server.lock'),
                       AGENT_TASKS_DB=str(folder/'tasks.db'),AGENT_TASKS_HOST='127.0.0.1')
            commands=[[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/memory_server.py')],
                      [NODE,str(ROOT/'agent-tasks/node_modules/agent-tasks/dist/server.js'),'--port','13422','--db',str(folder/'tasks.db')]]
            processes=[]
            with (ROOT/'runtime/verify-servers.log').open('w') as log:
                try:
                    for command in commands:processes.append(subprocess.Popen(command,env=env,cwd=folder,stdout=log,stderr=log))
                    for port,path in [(18765,'/api/health'),(13422,'/health')]:
                        for _ in range(120):
                            assert all(p.poll() is None for p in processes),'Test server exited; runtime/verify-servers.log'
                            try:fetch(path,port=port,key='test-secret-only');break
                            except OSError:time.sleep(.5)
                        else:raise RuntimeError('Test startup timeout')
                    duplicate=subprocess.run(commands[0],env=env,cwd=folder,capture_output=True,text=True)
                    assert duplicate.returncode!=0 and 'already owns' in duplicate.stderr
                    asyncio.run(roundtrip(folder,env))
                    if use_native:native(folder,env)
                    assert json.loads(fetch('/api/memory-stats',port=18765,key='test-secret-only'))['model_cache_count']==1
                finally:
                    for p in processes:p.terminate()
                    for p in processes:
                        try:p.wait(timeout=30)
                        except subprocess.TimeoutExpired:p.kill();p.wait()
    finally:
        if restart:manage.start('memory')
    assert fingerprint(MEMDB)==before,'Production memories/embeddings changed'
    print('PASS: exclusive model lock and original memory/embedding preservation',flush=True)

def lifecycle():
    before=fingerprint(MEMDB)
    def cli(*args):return subprocess.run([str(ROOT/'cli.sh'),*args],check=True,capture_output=True,text=True)
    def pid(name):
        import re
        text=manage.ctl('print',manage.DOMAIN+'/'+manage.SERVICES[name][0]).stdout
        return int(re.search(r'\bpid = (\d+)',text).group(1))
    cli('stop')
    assert all(not manage.loaded(n) and not manage.ready(n) for n in manage.SERVICES)
    try:
        processes=[subprocess.Popen([str(ROOT/'cli.sh'),'start'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
        for p in processes:
            out,err=p.communicate(timeout=120)
            assert p.returncode==0,(out,err)
        previous={n:pid(n) for n in manage.SERVICES}
        cli('restart')
        assert all(pid(n)!=previous[n] for n in manage.SERVICES)
        for name in manage.SERVICES:
            previous=pid(name)
            manage.ctl('kill','SIGTERM',manage.DOMAIN+'/'+manage.SERVICES[name][0])
            for _ in range(180):
                try:
                    if pid(name)!=previous and manage.ready(name):break
                except (AttributeError,subprocess.CalledProcessError):pass
                time.sleep(.5)
            else:raise RuntimeError(name+': automatic recovery failed')
        assert fingerprint(MEMDB)==before
        print('PASS: stop, four concurrent starts, restart, KeepAlive recovery for both services, persistence',flush=True)
    finally:
        cli('start')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifecycle',action='store_true');parser.add_argument('--isolated',action='store_true');parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    if args.isolated or args.native:isolated(args.native)
    if args.lifecycle:lifecycle()
    live()
