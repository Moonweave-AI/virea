import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Moon} from '../components';
import {CinematicStage} from '../CinematicStage';
import {CinematicPageCam} from '../CinematicPageCam';
import {C, clamp, enter} from '../theme';
import {MotionWords} from '../SpatialLanguage';

type P = [number, number];
const curvePoint = (t: number, a: P, b: P, c: P, d: P): P => [
  (1 - t) ** 3 * a[0] + 3 * (1 - t) ** 2 * t * b[0] + 3 * (1 - t) * t ** 2 * c[0] + t ** 3 * d[0],
  (1 - t) ** 3 * a[1] + 3 * (1 - t) ** 2 * t * b[1] + 3 * (1 - t) * t ** 2 * c[1] + t ** 3 * d[1],
];

const Flow: React.FC<{f: number; from: P; controlA: P; controlB: P; to: P; start: number; rose?: boolean}> = ({f, from, controlA, controlB, to, start, rose = false}) => {
  const p = curvePoint(clamp(f, start + 32, start + 106), from, controlA, controlB, to);
  const color = rose ? C.rose : C.silver;
  return <g>
    <path d={`M${from.join(' ')}C${controlA.join(' ')} ${controlB.join(' ')} ${to.join(' ')}`} fill="none" stroke={color} strokeOpacity="0.35" strokeWidth="2" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - enter(f, start, 42)} />
    <circle cx={to[0]} cy={to[1]} r="4" fill={color} opacity={enter(f, start + 32, 20)} />
    <g opacity={enter(f, start + 28, 12) * (1 - enter(f, start + 102, 13))}>
      <circle cx={p[0]} cy={p[1]} r="12" fill={color} fillOpacity="0.1" /><circle cx={p[0]} cy={p[1]} r="4.5" fill={color} />
    </g>
  </g>;
};

const InputNode: React.FC<{f: number; y: number; start: number; name: string; description: string; icon: 'intent' | 'voice' | 'motion'}> = ({f, y, start, name, description, icon}) => {
  const p = enter(f, start, 27);
  return <div style={{position: 'absolute', left: 96, top: y, width: 430, height: 122, display: 'flex', gap: 23, alignItems: 'center', padding: '24px 28px', boxSizing: 'border-box', borderBottom: `1px solid ${C.line}`, opacity: p, transform: `translate3d(${-35 * (1 - p)}px, 0, ${20 * p}px)`}}>
    <svg width="46" height="46" viewBox="0 0 46 46" style={{flexShrink: 0}}>
      {icon === 'intent' && <g fill="none" stroke={C.silver} strokeWidth="1.6"><path d="M9 10h28v21H22l-8 6v-6H9Z" strokeLinejoin="round" /><path d="M16 18h14M16 24h9" /></g>}
      {icon === 'voice' && <g stroke={C.rose} strokeWidth="2.2" strokeLinecap="round"><path d="M5 20v6M12 13v20M19 7v32M26 16v14M33 11v24M40 20v6" /></g>}
      {icon === 'motion' && <g fill="none" stroke={C.silver} strokeWidth="1.8" strokeLinecap="round"><circle cx="23" cy="8" r="4" /><path d="M23 13v15M8 15l15 4 15-4M23 28 13 39M23 28 33 39" /><circle cx="23" cy="27" r="2.5" fill={C.rose} stroke="none" /></g>}
    </svg>
    <div><div style={{fontSize: 37, fontWeight: 600, letterSpacing: -0.5}}>{name}</div><div style={{fontSize: 23, color: C.muted, marginTop: 8}}>{description}</div></div>
  </div>;
};

const OutputNode: React.FC<{f: number; y: number; start: number; vr?: boolean}> = ({f, y, start, vr = false}) => {
  const p = enter(f, start, 28);
  return <div style={{position: 'absolute', left: 1384, top: y, width: 440, height: 159, boxSizing: 'border-box', borderBottom: `1px solid ${C.line}`, padding: '24px 26px', opacity: p, transform: `translate3d(${35 * (1 - p)}px, 0, ${20 * p}px)`}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 15}}>
      <svg width="35" height="35" viewBox="0 0 35 35">
        {vr ? <g fill="none" stroke={C.silver} strokeWidth="1.6"><path d="M7 10h21l3 16H21l-3.5-5L14 26H4Z" strokeLinejoin="round" /><path d="M8 8l2-3h15l2 3" /><circle cx="10" cy="17" r="3" /><circle cx="25" cy="17" r="3" /></g> : <g fill="none" stroke={C.silver} strokeWidth="1.6"><rect x="3" y="5" width="29" height="20" rx="3" /><path d="M12 30h11M17.5 25v5M4 11h27" /></g>}
      </svg>
      <span style={{fontSize: vr ? 30 : 33, fontWeight: 600, letterSpacing: -0.5}}>{vr ? 'VRChat Humanoid' : 'Browser VRM'}</span>
    </div>
    <div style={{fontSize: 22, color: C.muted, marginTop: 22}}>{vr ? 'VRChat Studio · AI character' : 'Motion Lab / Character Studio'}</div>
  </div>;
};

export const ArchitectureScene: React.FC<{duration?: number}> = ({duration = 420}) => {
  const frame = useCurrentFrame();
  const f = (frame * 420) / Math.max(1, duration);
  const central = enter(f, 20, 29);
  return <CinematicStage>
    <div style={{position: 'absolute', left: 96, top: 64, fontSize: 20, letterSpacing: 3, color: C.silver}}><MotionWords text="ONE RUNTIME. MULTIPLE EMBODIMENTS."/></div>
    <div style={{position: 'absolute', left: 96, top: 110, fontSize: 57, fontWeight: 550, letterSpacing: -1.7}}><MotionWords text="Intelligence, voice, and motion. Connected." start={15}/></div>
    <div style={{position: 'absolute', right: 96, top: 75, fontSize: 20, color: C.muted}}>Concept illustration</div>
    <CinematicPageCam frame={f} keys={[
      {frame: 0, cx: 960, cy: 570, zoom: 0.6, rotX: 52, rotY: -28},
      {frame: 65, cx: 960, cy: 560, zoom: 0.87, rotX: 14, rotY: -16},
      {frame: 151, cx: 935, cy: 548, zoom: 0.88, rotX: 6, rotY: -6},
      {frame: 264, cx: 985, cy: 548, zoom: 0.88, rotX: 6, rotY: 8},
      {frame: 355, cx: 960, cy: 540, zoom: 0.94, rotX: 0, rotY: 0},
      {frame: 420, cx: 960, cy: 540, zoom: 0.94, rotX: 0, rotY: 0},
    ]}>
    <div style={{position: 'absolute', left: 96, top: 324, fontSize: 24, color: C.muted, letterSpacing: 2, opacity: enter(f, 17, 22)}}>Capability sources</div>
    <div style={{position: 'absolute', left: 1384, top: 324, fontSize: 24, color: C.muted, letterSpacing: 2, opacity: enter(f, 99, 22)}}>Execution targets</div>

    <svg width="1920" height="920" style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none'}}>
      {[0,1,2].map(i=><ellipse key={i} cx="960" cy="610" rx={590+i*150} ry={170+i*85} fill="none" stroke={C.silver} strokeOpacity={.08*enter(f,12+i*8,60)} strokeDasharray={i===1?'2 14':undefined}/>) }
      {Array.from({length:38},(_,i)=>{const a=i*2.39996;return <circle key={i} cx={960+Math.cos(a)*(660+(i%3)*75)} cy={610+Math.sin(a)*(235+(i%3)*43)} r={i%5===0?3:1.5} fill={i%5===0?C.rose:C.silver} opacity={.3*enter(f,i,35)}/>;})}
      <Flow f={f} from={[526, 446]} controlA={[600, 446]} controlB={[600, 590]} to={[656, 590]} start={51} />
      <Flow f={f} from={[526, 613]} controlA={[588, 613]} controlB={[610, 590]} to={[656, 590]} start={68} rose />
      <Flow f={f} from={[526, 780]} controlA={[600, 780]} controlB={[600, 590]} to={[656, 590]} start={85} />
      <path d="M656 410V776M1264 410V776" fill="none" stroke={C.silver} strokeOpacity={0.24 * enter(f, 67, 42)} strokeWidth={1.5} />
      <Flow f={f} from={[1264, 590]} controlA={[1324, 590]} controlB={[1310, 480]} to={[1384, 480]} start={143} />
      <Flow f={f} from={[1264, 590]} controlA={[1324, 590]} controlB={[1310, 714]} to={[1384, 714]} start={161} rose />
    </svg>

    <InputNode f={f} y={385} start={22} name="LLM" description="Intent and planning" icon="intent" />
    <InputNode f={f} y={552} start={37} name="TTS" description="Voice and rhythm" icon="voice" />
    <InputNode f={f} y={719} start={52} name="Motion" description="Native skeleton data" icon="motion" />

    <div style={{position: 'absolute', left: 670, top: 280, width: 580, height: 545, transformStyle: 'preserve-3d', opacity: central}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 20, paddingLeft: 30, transform: 'translateZ(38px)'}}><Moon size={44} /><div><span style={{fontSize: 43, fontWeight: 600, letterSpacing: 2}}>VIREA</span><span style={{fontSize: 19, letterSpacing: 3, color: C.silver, marginLeft: 19}}>RUNTIME</span></div></div>
      {[
        {name: 'MotionIR v2', description: 'Motion schema', color: C.silver},
        {name: 'Timeline', description: 'Orchestration', color: C.rose},
        {name: 'Retargeting', description: 'Joint transforms', color: C.silver},
        {name: 'Execution receipts', description: 'Evidence', color: C.silver},
      ].map((layer, index) => {
        const start = 55 + index * 18;
        const arrive = enter(f, start, 36);
        const active = enter(f, 115 + index * 28, 14) * (1 - enter(f, 152 + index * 28, 28));
        const height = 28 + (3 - index) * 35 + 130 * (1 - arrive);
        return <div key={layer.name} style={{position: 'absolute', left: 0, top: 110 + index * 102, width: 580, height: 82, padding: '0 28px', boxSizing: 'border-box', display: 'flex', gap: 17, alignItems: 'center', transform: `translate3d(0, ${36 * (1 - arrive)}px, ${height}px)`, opacity: arrive,
          background: 'linear-gradient(120deg, #2a2b3af5, #1b1c29f5)', border: `1px solid ${active > 0.2 ? '#c9adb890' : '#bdb8d133'}`, borderRadius: 13,
          boxShadow: `0 ${15 + 14 * (1 - arrive)}px ${25 + 20 * (1 - arrive)}px #08091255, inset 0 1px 0 #f2edf115`,
        }}><span style={{fontSize: 16, color: C.muted, width: 22}}>0{index + 1}</span><span style={{width: 6, height: 6, borderRadius: '50%', background: layer.color, boxShadow: active > 0.2 ? `0 0 10px ${layer.color}50` : undefined}} /><span style={{fontSize: 28, fontWeight: 500}}>{layer.name}</span><span style={{fontSize: 19, color: C.muted, marginLeft: 'auto'}}>{layer.description}</span></div>;
      })}
    </div>

    <OutputNode f={f} y={401} start={116} />
    <OutputNode f={f} y={635} start={134} vr />
    </CinematicPageCam>
  </CinematicStage>;
};
