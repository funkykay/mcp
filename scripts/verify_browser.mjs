// Optional browser verification, using external Playwright (no runtime dependency).
// Production pages are read-only. Live-update writes use a temporary task DB.
import { pathToFileURL } from 'node:url';
if (!process.env.TEST_PLAYWRIGHT || !process.env.TEST_CHROMIUM)
  throw Error('Set TEST_PLAYWRIGHT to playwright-core/index.mjs and TEST_CHROMIUM to the browser executable');
const { chromium } = await import(pathToFileURL(process.env.TEST_PLAYWRIGHT).href);
import Database from '../agent-tasks/node_modules/better-sqlite3/lib/index.js';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const folder=await mkdtemp(join(tmpdir(),'mcp-browser-'));
const source=new Database(join(root,'agent-tasks/data/agent-tasks.db'),{readonly:true});
await source.backup(join(folder,'tasks.db'));source.close();
const child=spawn(process.execPath,[join(root,'agent-tasks/node_modules/agent-tasks/dist/server.js'),'--port','13422','--db',join(folder,'tasks.db')],{env:{...process.env,AGENT_TASKS_HOST:'127.0.0.1'},stdio:'ignore'});
let browser;
try {
  for(let i=0;i<80;i++) {
    try { if((await fetch('http://127.0.0.1:13422/health')).ok)break; } catch {}
    await new Promise(r=>setTimeout(r,250));
  }
  browser=await chromium.launch({executablePath:process.env.TEST_CHROMIUM,headless:true});
  const memory=await browser.newPage();
  const errors=[];memory.on('pageerror',e=>errors.push(String(e)));
  await memory.goto('http://127.0.0.1:8000');
  await memory.locator('#apiKeyInput').fill((await readFile(join(root,'runtime/api-key'),'utf8')).trim());
  const authenticated=memory.waitForResponse(r=>r.url().includes('/api/') && r.status()===200);
  await memory.locator('#authWithApiKey').click();await authenticated;
  await memory.waitForFunction(()=>localStorage.getItem('mcp_api_key'));
  const actual=await memory.evaluate(async()=>{
    const r=await fetch('/api/memories',{headers:{'X-API-Key':localStorage.getItem('mcp_api_key')}});
    return {status:r.status,data:await r.json()};
  });
  if(actual.status!==200)throw Error('Memory authenticated data failed');
  await memory.screenshot({path:join(root,'runtime/memory-dashboard.png')});
  const tasks=await browser.newPage();tasks.on('pageerror',e=>errors.push(String(e)));
  const frames=[];tasks.on('websocket',ws=>ws.on('framereceived',f=>frames.push(f.payload)));
  await tasks.goto('http://127.0.0.1:3422');
  await tasks.locator('.task-card').first().waitFor();
  const taskId=await tasks.locator('.task-card').first().getAttribute('data-task-id');
  await tasks.screenshot({path:join(root,'runtime/tasks-dashboard.png')});
  await tasks.goto('http://127.0.0.1:13422');
  await tasks.locator(`.task-card[data-task-id="${taskId}"]`).waitFor();
  const res=await fetch(`http://127.0.0.1:13422/api/tasks/${taskId}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Browser isolated live update'})});
  if(!res.ok)throw Error('Isolated task update failed');
  const comment=await fetch(`http://127.0.0.1:13422/api/tasks/${taskId}/comments`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:'Force distinct live-update fingerprint',author:'isolated-test'})});
  if(!comment.ok)throw Error('Isolated comment failed');
  await tasks.locator(`.task-card[data-task-id="${taskId}"]`).filter({hasText:'Browser isolated live update'}).waitFor({timeout:15000});
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({result:'PASS',memoryLogin:true,memoryData:actual.data.total ?? actual.data.memories?.length,productionTaskCard:true,isolatedWebSocketUpdate:true,websocketFrames:frames.length,browserErrors:errors}));
} finally {
  if(browser)await browser.close();
  child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));
  await rm(folder,{recursive:true,force:true});
}
