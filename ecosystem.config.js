const path = require("node:path");

const arisDir = __dirname;
const arisPython = process.env.ARIS_PYTHON || path.join(arisDir, ".venv", "bin", "python");

module.exports = {
    apps: [
        {
            name: 'aris-api',
            cwd: arisDir,
            script: arisPython,
            args: '-m apps.api.main',
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
