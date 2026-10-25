// Local entrypoint: upstream stdio MCP, without its implicit dashboard listener.
// Keep all domain logic and tool definitions in the pinned upstream package.
import { startMcpServer } from 'agent-common';
import { createContext } from './node_modules/agent-tasks/dist/context.js';
import { tools, createToolHandler } from './node_modules/agent-tasks/dist/transport/mcp.js';
import { readPackageMeta } from './node_modules/agent-tasks/dist/package-meta.js';

const ctx = createContext();
const handleTool = createToolHandler(ctx);
const identity = `${process.env.TASK_AGENT || 'cli'}-${process.pid}`;
handleTool('task_config', { action: 'session', id: identity, name: identity });
const server = startMcpServer({ serverInfo: readPackageMeta(), tools, handleTool, logLabel: 'agent-tasks' });
let closing = false;
function close() {
  if (closing) return;
  closing = true;
  server.close();
  ctx.close();
}
process.stdin.on('end', () => { close(); process.exit(0); });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { close(); process.exit(0); });
process.on('exit', close);
