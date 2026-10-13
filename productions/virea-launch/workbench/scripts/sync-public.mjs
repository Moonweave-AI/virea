import {cpSync, existsSync, lstatSync, mkdirSync, readdirSync, realpathSync, rmSync} from 'node:fs';
import {dirname, join, resolve, relative, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const wb=resolve(dirname(fileURLToPath(import.meta.url)), '..');
const destination=resolve(wb,'.render-public');
// Only replace our generated real directory; never follow a junction for deletion.
if(relative(wb,destination)!=='.render-public') throw new Error('Unsafe render asset destination.');
if(existsSync(destination)){
  if(lstatSync(destination).isSymbolicLink() || !realpathSync(destination).startsWith(realpathSync(wb)+sep)) throw new Error('Render destination is outside this workbench.');
  rmSync(destination,{recursive:true,force:true});
}
mkdirSync(destination,{recursive:true});
for(const name of readdirSync(join(wb,'public'))){
  if(name.startsWith('.') || name==='cardpreviews') continue;
  cpSync(join(wb,'public',name),join(destination,name),{recursive:true,dereference:true});
}
console.log('Current film assets synchronized for export.');
