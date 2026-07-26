const path = require("node:path");

const arisDir = __dirname;
const workspaceDir = path.dirname(arisDir);
const workerDir = process.env.ARIS_WORKER_DIR || path.join(workspaceDir, "aiida-worker");
const arisPython = process.env.ARIS_PYTHON || path.join(arisDir, ".venv", "bin", "python");

module.exports = {
    apps: [
        {
            name: 'aiida-worker',
            cwd: workerDir,
            script: 'uv',
            args: 'run uvicorn main:app --host 127.0.0.1 --port 8001',
            interpreter: 'none',
            env: {
                PYTHONPATH: '.'
            }
        },
        {
            name: 'aris-api',
            cwd: arisDir,
            script: arisPython,
            args: 'app_api.py',
            env: {
                PYTHONPATH: arisDir
            }
        },
        {
            name: 'aris-web',
            cwd: path.join(arisDir, 'frontend'),
            script: 'npm',
            args: 'run dev -- --host 127.0.0.1 --port 5173',
        },
        {
            name: "aris-tunnel",
            script: "cloudflared",
            args: `tunnel run ${process.env.ARIS_TUNNEL_NAME || "aris-aiida-tunnel"}`,
            autorestart: true
        }
    ]
};
