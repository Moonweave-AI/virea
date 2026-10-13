import {spawn,spawnSync} from 'node:child_process';
import {existsSync,openSync,writeFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const wb=resolve(dirname(fileURLToPath(import.meta.url)),'..');
for(const script of ['link-project.mjs','gen-index.mjs']){
  const result=spawnSync(process.execPath,[join(wb,'scripts',script)],{cwd:wb,stdio:'inherit',windowsHide:true});
  if(result.status!==0) process.exit(result.status??1);
}
const url='http://127.0.0.1:5198/';
const alive=async()=>{try{const r=await fetch(url+'api/workbench/health',{signal:AbortSignal.timeout(1000)});return r.ok&&(await r.json()).kind==='virea-launch-workbench';}catch{return false;}};
if(await alive()){console.log(`Workbench already listening: ${url}?import=project`);process.exit(0);}
try {
  const r=await fetch(url,{signal:AbortSignal.timeout(1000)});
  if(r.ok) throw new Error('Port 5198 belongs to another service. Stop that service or choose another workbench port before starting.');
} catch(error) {
  if(error instanceof Error && error.message.startsWith('Port 5198')) throw error;
}
const vite=join(wb,'node_modules/vite/bin/vite.js');
if(!existsSync(vite))throw new Error('Run npm install first.');
const fd=openSync(join(wb,'.dev.log'),'a');
const child=spawn(process.execPath,[vite,'--host','127.0.0.1','--port','5198','--strictPort'],{cwd:wb,detached:true,windowsHide:true,stdio:['ignore',fd,fd]});
child.unref();writeFileSync(join(wb,'.dev.pid'),String(child.pid));
for(let attempt=0;attempt<60;attempt++){
  if(await alive()){console.log(`English workbench, silent preview: ${url}?import=project`);process.exit(0);}
  await new Promise(r=>setTimeout(r,500));
}
throw new Error('Workbench failed to start; inspect .dev.log.');
