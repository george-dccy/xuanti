const path = require("node:path");

const root = path.resolve(__dirname, "..", "..");

module.exports = {
  apps: [
    {
      name: "creatorhub",
      cwd: root,
      script: path.join(root, "creatorhub.py"),
      interpreter: path.join(root, ".venv", "bin", "python"),
      args: "start --host 127.0.0.1 --port 18000 --no-open --skip-install",
      exec_mode: "fork",
      instances: 1,
      autorestart: true,
      watch: false,
      restart_delay: 5000,
      kill_timeout: 10000,
      max_memory_restart: "1500M",
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
        TZ: "Asia/Shanghai",
      },
    },
  ],
};
