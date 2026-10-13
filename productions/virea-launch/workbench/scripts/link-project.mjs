import {existsSync, mkdirSync, readdirSync, realpathSync, symlinkSync, copyFileSync} from 'node:fs';
import {dirname, join, resolve, relative, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const wb = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const project = resolve(wb, '../edit');
const production = resolve(wb, '..');
const inside = (p, root) => {const r = relative(root, p); return r === '' || (!r.startsWith(`..${sep}`) && r !== '..' && !/^[A-Za-z]:/.test(r));};
if (!inside(realpathSync(project), realpathSync(production))) throw new Error('Film project must stay inside this production.');
const directoryLink = (target, destination) => {
  if (!inside(resolve(destination), wb) || !inside(realpathSync(target), realpathSync(project))) throw new Error('Link outside the production.');
  if (existsSync(destination)) {
    if (realpathSync(destination) !== realpathSync(target)) throw new Error(`Refusing to replace existing path: ${destination}`);
    return;
  }
  symlinkSync(target, destination, process.platform === 'win32' ? 'junction' : 'dir');
};
directoryLink(join(project, 'src'), join(wb, 'proj'));
mkdirSync(join(wb, 'public'), {recursive: true});
for (const entry of readdirSync(join(project, 'public'), {withFileTypes: true})) {
  if (entry.name.startsWith('.')) continue;
  const source = join(project, 'public', entry.name);
  const target = join(wb, 'public', entry.name);
  if (entry.isDirectory()) directoryLink(source, target);
  else if (entry.isFile()) copyFileSync(source, target);
}
mkdirSync(join(wb, 'demosrc'), {recursive: true});
console.log('Linked the current film source and assets. No administrator privileges required.');
