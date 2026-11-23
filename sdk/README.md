# `@lattis/client`

Zero-dependency TypeScript client SDK for connecting desktop apps (Tauri, Electron), web apps, or scripts to a **Lattis v2 Daemon**.

## Quick Start

```ts
import { LattisClient } from "@lattis/client";

const client = new LattisClient({
  baseUrl: "http://127.0.0.1:7700",
  token: process.env.LATTIS_API_TOKEN // or read ~/.lattis/auth.token
});

const workspace = await client.registerWorkspace("/path/to/my-repo");
const thread = await client.createThread(workspace.id);

const controller = new AbortController();
void client.subscribeEvents({
  workspaceId: workspace.id,
  signal: controller.signal,
  onEvent: (event) => {
    if (event.type === "item.delta") {
      process.stdout.write(event.data.delta);
    }
  }
});

await client.startRun(thread.id, "Summarize recent git changes");
```

## Regenerate OpenAPI Types & Build

```bash
npm run gen:openapi
npm run build
```
