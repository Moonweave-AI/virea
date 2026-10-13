import {bundle} from '@remotion/bundler';
import {selectComposition} from '@remotion/renderer';
import {spawnSync} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const wb=resolve(dirname(fileURLToPath(import.meta.url)),'..');
for(const script of ['link-project.mjs','gen-index.mjs','sync-public.mjs']){
  const r=spawnSync(process.execPath,[join(wb,'scripts',script)],{cwd:wb,stdio:'inherit',windowsHide:true});
  if(r.status!==0)process.exit(r.status??1);
}
const serveUrl=await bundle({
  entryPoint:join(wb,'src/remotion/index.ts'),
  publicDir:join(wb,'.render-public'),
  webpackOverride:(config)=>({...config,resolve:{...config.resolve,symlinks:false,alias:{...(config.resolve?.alias??{}),'@proj':join(wb,'proj'),'@demos':join(wb,'demosrc')}}}),
});
const composition=await selectComposition({serveUrl,id:'ProjImported',inputProps:{}});
const project=composition.defaultProps?.project;
if(!project?.tracks?.length)throw new Error('The current manifest did not produce an editable project.');
mkdirSync(join(wb,'projects'),{recursive:true});
const output=join(wb,'projects/virea-english.json');
writeFileSync(output,JSON.stringify(project,null,2)+'\n');
console.log(`Saved ${project.tracks.reduce((n,track)=>n+track.clips.length,0)} editable clips, ${composition.durationInFrames} frames at ${composition.fps} fps: ${output}`);
