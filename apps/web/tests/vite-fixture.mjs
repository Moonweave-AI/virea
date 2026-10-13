import {mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createServer as createViteServer} from "vite";

// Parallel test servers must not rename the same Vite dependency cache.
export async function createServer(options) {
  const cacheDir = await mkdtemp(join(tmpdir(), "virea-vite-test-"));
  try {
    const server = await createViteServer({...options, cacheDir});
    const close = server.close.bind(server);
    server.close = async () => {
      try { await close(); }
      finally { await rm(cacheDir, {recursive:true, force:true}); }
    };
    return server;
  } catch (error) {
    await rm(cacheDir, {recursive:true, force:true});
    throw error;
  }
}
