import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {CinematicStage} from '../CinematicStage';
import {CinematicPageCam} from '../CinematicPageCam';
import {CinematicClipCard} from '../CinematicClipCard';
import {ASSETS} from '../Assets';
import {MotionWords, MotionLandscape, StudioRing, travel} from '../SpatialLanguage';
import {C, FONT, clamp, enter} from '../theme';

const settle = Easing.bezier(0.34, 1.12, 0.44, 1);
const smooth = Easing.bezier(0.33, 0, 0.15, 1);
const motion = (f: number, start: number, end: number, from: number, to: number, easing = smooth) => interpolate(f, [start, end], [from, to], {
  extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing,
});

const WordReveal: React.FC<{f: number; start: number; children: React.ReactNode; color?: string}> = ({f, start, children, color = C.ink}) => {
  const p = enter(f, start, 34);
  return <div style={{overflow: 'hidden', color}}><div style={{transform: `translateY(${105 * (1 - p)}%)`, opacity: clamp(f, start, start + 12)}}>{children}</div></div>;
};

const MetalWordmark: React.FC<{f: number; start: number; size?: number}> = ({f, start, size = 180}) => <div style={{display: 'flex', justifyContent: 'center', fontFamily: FONT, fontSize: size, fontWeight: 550, lineHeight: 1.12, letterSpacing: size * 0.07, perspective: 1600}}>
  {'VIREA'.split('').map((letter, index) => {
    const t = enter(f, start + index * 5, 36);
    return <span key={letter} style={{position: 'relative', display: 'inline-block', opacity: clamp(f, start + index * 5, start + index * 5 + 12), transform: `translateY(${56 * (1 - t)}px) rotateX(${35 * (1 - t)}deg)`, transformOrigin: '50% 100%', transformStyle: 'preserve-3d'}}>
      <span aria-hidden style={{position: 'absolute', inset: 0, color: '#686579', transform: 'translate3d(0, 3px, -4px)', textShadow: '0 12px 24px #00000050'}}>{letter}</span>
      <span style={{position: 'relative', background: 'linear-gradient(156deg, #f3eef2 14%, #bdb8d1 49%, #d4bcc9 81%)', backgroundClip: 'text', WebkitBackgroundClip: 'text', color: 'transparent'}}>{letter}</span>
    </span>;
  })}
</div>;

const STUDIO_SURFACES = [
  {name: 'Motion Lab', subtitle: 'Explore the motion', poster: ASSETS.lab, accent: C.silver, x: 120},
  {name: 'Character Studio', subtitle: 'Bring a character to life', poster: 'captures/character-full-new.png', accent: C.rose, x: 710},
  {name: 'VRChat Studio', subtitle: 'Enter a shared world', poster: ASSETS.ai.poster, accent: C.silver, x: 1300},
] as const;

const StudioSurface: React.FC<{index: number; f: number; start: number; y: number; opacity?: number; compact?: number}> = ({index, f, start, y, opacity = 1, compact = 1}) => {
  if (opacity <= 0 || f < start) return null;
  const surface = STUDIO_SURFACES[index];
  const p = motion(f, start, start + 48, 0, 1, settle);
  const side = index - 1;
  const airborne = Math.max(0, 1 - p);
  return <div style={{position: 'absolute', left: surface.x, top: y, width: 500, opacity: opacity * clamp(f, start, start + 12), transformOrigin: '50% 50%', transformStyle: 'preserve-3d', transform: `translate3d(${side * 390 * (1 - p)}px, ${170 * (1 - p)}px, ${80 * airborne}px) rotateY(${-side * 16 * (1 - p)}deg) rotateZ(${side * 4 * (1 - p)}deg) scale(${compact})`}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 13, marginBottom: 18, fontSize: 28, fontWeight: 520}}><span style={{width: 7, height: 7, borderRadius: '50%', background: surface.accent}} />{surface.name}</div>
    <CinematicClipCard poster={surface.poster} width={500} height={282} radius={11} />
    <div style={{marginTop: 21, fontSize: 22, color: C.muted}}>{surface.subtitle}</div>
  </div>;
};

/** The requested banner opens as a complete cover, then lifts into the data landscape. */
export const OpeningScene: React.FC<{duration?: number}> = ({duration = 255}) => {
  const f=useCurrentFrame(); const release=travel(f,135,205);
  const sway=Math.sin(Math.PI*travel(f,0,135));
  const arrival=travel(f,0,55);
  return <CinematicStage floor={false}>
    <MotionLandscape frame={Math.max(0,f-105)}/>
    <AbsoluteFill style={{perspective:2200,perspectiveOrigin:'50% 48%'}}>
      <div style={{position:'absolute',left:34,top:52,width:1852,height:926,transformOrigin:'50% 70%',transform:`translate3d(${14*sway}px,${-320*release}px,${-1000*release-250*(1-arrival)}px) rotateY(${18*(1-arrival)-5*sway}deg) rotateX(${55*release-8*(1-arrival)}deg)`,opacity:1-travel(f,184,210),boxShadow:'0 35px 100px #000a'}}>
        <Img src={staticFile('art/brand-cover-v2.png')} style={{width:'100%',height:'100%',objectFit:'contain'}}/>
        <div style={{position:'absolute',inset:0,background:`linear-gradient(112deg,transparent ${travel(f,10,120,-25,115)-12}%,#ede5f01f ${travel(f,10,120,-25,115)}%,transparent ${travel(f,10,120,-25,115)+12}%)`,mixBlendMode:'screen'}}/>
      </div>
    </AbsoluteFill>
    <div style={{position:'absolute',left:125,top:116,opacity:travel(f,176,195)}}>
      <div style={{fontSize:26,letterSpacing:4,color:C.silver}}><MotionWords text="FROM AVATARS TO AGENTS" start={179}/></div>
      <div style={{fontSize:91,fontWeight:550,letterSpacing:-3,lineHeight:1.16,marginTop:28}}><MotionWords text="Characters that move." start={185}/><br/><MotionWords text="Interactions that matter." start={198} style={{color:C.rose}}/></div>
    </div>
  </CinematicStage>;
};

export const BrandScene: React.FC<{duration?: number}> = ({duration = 330}) => <CinematicStage>
  <StudioRing duration={duration}/>
  <div style={{position:'absolute',top:60,width:'100%',textAlign:'center',fontSize:58,fontWeight:550,letterSpacing:-1.5}}><MotionWords text="One foundation. Multiple embodiments."/></div>
  <div style={{position:'absolute',top:145,width:'100%',textAlign:'center',fontSize:26,color:C.silver}}><MotionWords text="Explore motion. Meet your character. Enter the world." start={26}/></div>
</CinematicStage>;

/** A finite product group-photo resolves into one clean sign-off. */
export const ClosingScene: React.FC<{duration?: number}> = ({duration = 450}) => {
  const f = useCurrentFrame() * 450 / Math.max(1, duration);
  const retire = motion(f, 110, 166, 0, 1);
  const plate = enter(f, 210, 105);
  return <CinematicStage floor={false}>
    <AbsoluteFill style={{opacity: 0.35 * plate}}><Img src={staticFile('art/lunar-world.png')} style={{width: '100%', height: '100%', objectFit: 'cover'}} /></AbsoluteFill>
    <AbsoluteFill style={{background: 'linear-gradient(90deg, #11121b00, #11121b00 48%, #11121b40)'}} />
    <CinematicPageCam frame={f} keys={[
      {frame: 0, cx: 1080, cy: 570, zoom: 0.66, rotX: 28, rotY: 32},
      {frame: 85, cx: 960, cy: 540, zoom: 1, rotX: 0, rotY: 0},
      {frame: 278, cx: 960, cy: 520, zoom: 1.016, rotX: 0, rotY: 0},
      {frame: 450, cx: 960, cy: 520, zoom: 1.016, rotX: 0, rotY: 0},
    ]}>
      <div style={{position: 'absolute', top: 81, width: '100%'}}><MetalWordmark f={f + 200} start={0} size={135} /></div>
      {STUDIO_SURFACES.map((surface, index) => <StudioSurface key={surface.name} index={index} f={f + 100} start={0} y={318 + 275 * retire} opacity={1 - retire} compact={1 - 0.16 * retire} />)}
      <div style={{position: 'absolute', top: 302, left: 0, width: '100%', textAlign: 'center', fontSize: 104, letterSpacing: -3.7, lineHeight: 1.13, fontWeight: 500}}>
        <WordReveal f={f} start={168}>Bring your avatars</WordReveal>
        <WordReveal f={f} start={190} color={C.rose}>to life.</WordReveal>
      </div>
      <div style={{position: 'absolute', top: 606, width: '100%', textAlign: 'center', fontSize: 37, letterSpacing: -0.6, opacity: enter(f, 244, 36)}}>github.com/Moonweave-AI/virea <span style={{color: C.rose, marginLeft: 12}}>↗</span></div>
      <div style={{position: 'absolute', left: 0, top: 735, width: '100%', textAlign: 'center', opacity: enter(f, 295, 30)}}>
        <div style={{fontSize: 24, color: C.silver}}>Browser studios on Windows, Linux, and macOS.</div>
        <div style={{fontSize: 21, color: C.muted, marginTop: 15}}>VRChat Studio on Windows.</div>
        <div style={{fontSize: 18, color: C.muted, marginTop: 30}}>Character: Reira · Music: Lily J</div>
      </div>
    </CinematicPageCam>
  </CinematicStage>;
};
