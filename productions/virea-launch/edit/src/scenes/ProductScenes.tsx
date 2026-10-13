import React from 'react';
import {MotionWords, SideGlide} from '../SpatialLanguage';
import {AbsoluteFill, Easing, Freeze, Img, Sequence, staticFile, interpolate, useCurrentFrame} from 'remotion';
import {CinematicStage} from '../CinematicStage';
import {CinematicPageCam} from '../CinematicPageCam';
import {CinematicClipCard} from '../CinematicClipCard';
import {C, enter} from '../theme';

export type ProductClip = {src:string; frames?:number; trimBefore?:number; poster?:string; fit?:'contain'|'cover'; sourceWidth?:number; sourceHeight?:number};
const smooth = Easing.bezier(0.6,0,0.18,1);
const move = (f:number,a:number,b:number,x:number,y:number) => interpolate(f,[a,b],[x,y],{easing:smooth,extrapolateLeft:'clamp',extrapolateRight:'clamp'});

/** Title Demote, form A: one continuous position/scale curve, no UI fragments. */
const Chapter:React.FC<{name:string; subtitle?:string; demote?:boolean}> = ({name,subtitle,demote=false}) => {
  const f=useCurrentFrame(); const p=demote?move(f,36,62,0,1):1;
  return <>
    <div style={{position:'absolute',left:960+(140-960)*p,top:490+(25-490)*p,transform:`translate(${-50*(1-p)}%,-50%) scale(${1-.78*p})`,transformOrigin:'left center',whiteSpace:'nowrap',fontSize:126,fontWeight:580,letterSpacing:-4,color:C.ink,opacity:enter(f,0,16)}}><MotionWords text={name}/><span style={{color:C.rose}}>.</span></div>
    {subtitle&&<div style={{position:'absolute',right:140,top:14,fontSize:19,color:C.silver,opacity:enter(f,demote?65:10,20)}}><MotionWords key={subtitle} text={subtitle} start={0}/></div>}
  </>;
};

const FullWindow:React.FC<{asset:ProductClip; f?:number; entrance?:'tilt'|'flat'|'rise'; start?:number; playbackDelay?:number}> = ({asset,f:frameOverride,entrance='tilt',start=0,playbackDelay=0}) => {
  const local=useCurrentFrame();const f=(frameOverride??local)-start;
  return <CinematicPageCam frame={f} keys={[
    {frame:0,cx:960,cy:entrance==='rise'?635:560,zoom:entrance==='flat'?.854:.59,rotX:entrance==='tilt'?28:0,rotY:entrance==='tilt'?-34:0},
    {frame:48,cx:960,cy:560,zoom:.854,rotX:0,rotY:0},
    {frame:96,cx:960,cy:560,zoom:.854,rotX:0,rotY:0},
  ]}>
    <Freeze frame={Math.max(0,local-playbackDelay)}><CinematicClipCard src={asset.src||undefined} poster={asset.poster??''} sourceFrames={asset.frames} startFrom={asset.trimBefore??0} radius={18}/></Freeze>
  </CinematicPageCam>;
};

export const MotionLabScene:React.FC<{duration?:number;screenshot?:string;video?:ProductClip;zoom?:number}> = ({screenshot='',video}) => {
  const f=useCurrentFrame();
  return <CinematicStage>
    <div style={{opacity:enter(f,48,24)}}><FullWindow asset={video??{src:'',poster:screenshot}} entrance="rise" start={48}/></div>
    <Chapter name="Motion Lab" subtitle="Source skeleton → retargeted avatar" demote/>
  </CinematicStage>;
};

/** A single inverse-pose flight joins two complete model workspaces. */
export const ModelsScene:React.FC<{duration?:number;prism?:ProductClip;senti?:ProductClip;motioncraft?:ProductClip;syntalker?:ProductClip;ardy?:ProductClip}> = ({duration=450,prism,senti}) => {
  const f=useCurrentFrame(); const k=duration/450;const flightStart=118*k,flightEnd=146*k;const t=move(f,flightStart,flightEnd,0,1);
  const poses=[{x:0,z:0,ry:0},{x:2500,z:-1000,ry:-34}];
  const reveal=move(f,58,66,0,1);
  const camera={x:2500*t,z:-1000*t,ry:-34*t};const zoom=.854/(1+.32*Math.sin(Math.PI*t));
  return <CinematicStage>
    <div style={{opacity:1-reveal}}><SideGlide frame={f} posters={[prism?.poster??'',senti?.poster??'']}/></div>
    <AbsoluteFill style={{opacity:reveal,perspective:2600,perspectiveOrigin:'960px 520px',overflow:'hidden'}}>
      <div style={{position:'absolute',left:960/zoom,top:522/zoom,width:0,height:0,transformStyle:'preserve-3d',zoom,transform:`rotateY(${-camera.ry}deg) translate3d(${-camera.x}px,0,${-camera.z}px)`}}>
        {[prism,senti].map((asset,i)=><div key={i} style={{position:'absolute',left:-960,top:-540,width:1920,height:1080,transformStyle:'preserve-3d',transform:`translate3d(${poses[i].x}px,0,${poses[i].z}px) rotateY(${poses[i].ry}deg)`}}>
          {asset&&<Freeze frame={Math.max(0,f-(i?flightEnd:36*k))}><CinematicClipCard src={asset.src} poster={asset.poster??''} sourceFrames={asset.frames} startFrom={asset.trimBefore??0}/></Freeze>}
        </div>)}
      </div>
    </AbsoluteFill>
    <Chapter name="Motion Lab" subtitle={t<.5?'PRISM · text → motion':'SentiAvatar · audio → body gestures'}/>
  </CinematicStage>;
};

export const CharacterScene:React.FC<{duration?:number;videoSrc?:string;posterSrc?:string;videoFrames?:number;trimBefore?:number;request?:string}> = ({videoSrc='footage/character-full-new.mp4',posterSrc='captures/character-full-new.png',videoFrames=480,trimBefore=0}) => <CinematicStage>
  <FullWindow asset={{src:videoSrc,poster:posterSrc,frames:videoFrames,trimBefore}} entrance="tilt" playbackDelay={48}/>
  <Chapter name="Character Studio" subtitle="A conversation becomes a performance"/>
</CinematicStage>;

/** Complete real pages on three spatial stations, using Basic3DScene's inverse pose. */
export const SetupScene:React.FC<{duration?:number;deviceCapture?:string;deploymentCapture?:string;verificationCapture?:string}> = ({duration=540,deviceCapture='',deploymentCapture='',verificationCapture=''}) => {
  const f=useCurrentFrame();const k=duration/360;
  const first=move(f,135*k,159*k,0,1),second=move(f,250*k,274*k,0,1);
  const x=2380*(first+second),z=-720*(first+second),ry=-32*first+64*second;
  const hop=.15*(Math.sin(Math.PI*first)+Math.sin(Math.PI*second));
  const zoom=.854/(1+hop);
  const poses=[{x:0,z:0,ry:0},{x:2380,z:-720,ry:-32},{x:4760,z:-1440,ry:32}];
  const active=second>.5?2:first>.5?1:0;
  return <CinematicStage>
    <AbsoluteFill style={{perspective:2800,perspectiveOrigin:'960px 520px',overflow:'hidden'}}>
      <div style={{position:'absolute',left:960/zoom,top:522/zoom,width:0,height:0,zoom,transformStyle:'preserve-3d',transform:`rotateY(${-ry}deg) rotateX(${move(f,0,52,46,0)}deg) translate3d(${-x}px,0,${-z}px)`}}>
        {[deviceCapture,deploymentCapture,verificationCapture].map((poster,i)=><div key={i} style={{position:'absolute',left:-960,top:-540,transform:`translate3d(${poses[i].x}px,0,${poses[i].z}px) rotateY(${poses[i].ry}deg)`,transformStyle:'preserve-3d'}}><CinematicClipCard poster={poster}/></div>)}
      </div>
    </AbsoluteFill>
    <Chapter name="Set Up" subtitle={['01   Detect your device','02   Connect a model','03   Verify a real result'][active]}/>
  </CinematicStage>;
};

/** Brand mascot with anatomical callouts; illustration is separate from real game capture. */
const TrackingIntro:React.FC<{duration:number}> = ({duration}) => {
  const f=useCurrentFrame(); const p=move(f,0,48,0,1);
  const orbit=move(f,45,duration-22,-6,6);
  const annotations=[
    {label:'Head',detail:'Position + orientation',x:1000,y:215,end:1280,ty:204},
    {label:'Hands',detail:'Generated wrist poses',x:856,y:470,end:520,ty:400},
    {label:'Body',detail:'Pelvis + torso tracking',x:975,y:405,end:1280,ty:462},
    {label:'Feet',detail:'Left + right foot targets',x:930,y:786,end:520,ty:758},
  ];
  return <div style={{position:'absolute',inset:0,perspective:2000}}><div style={{position:'absolute',inset:0,transformStyle:'preserve-3d',transform:`rotateY(${orbit}deg) translateZ(${move(f,48,duration-22,0,70)}px)`}}>
    <div style={{position:'absolute',left:700,top:134,width:520,height:710,transform:`translate3d(${60*(1-p)}px,${25*(1-p)}px,0) rotateY(${-18*(1-p)}deg)`,opacity:enter(f,0,12)}}>
      <Img src={staticFile('art/mascot-full-body.png')} style={{width:'100%',height:'100%',objectFit:'contain',filter:'drop-shadow(0 12px 42px #c9adb81a)'}}/>
    </div>
    <svg width="1920" height="940" viewBox="0 0 1920 940" style={{position:'absolute',inset:0}}>
      <ellipse cx="960" cy="845" rx="285" ry="35" fill="#bdb8d105" stroke="#c9adb825"/>
      {annotations.map((n,i)=>{const show=enter(f,42+i*40,30);return <g key={n.label} opacity={show}>
        <path d={`M${n.x} ${n.y} L${n.end+(n.end<960?155:-32)} ${n.ty} H${n.end}`} fill="none" stroke={C.rose} strokeWidth="1.5" pathLength="1" strokeDasharray="1" strokeDashoffset={1-show}/>
        <circle cx={n.x} cy={n.y} r="5" fill={C.rose}/>
        <text x={n.end<960?n.end-260:n.end+24} y={n.ty-13} fill={C.ink} fontSize="34" fontWeight="500">{n.label}</text>
        <text x={n.end<960?n.end-260:n.end+24} y={n.ty+22} fill={C.silver} fontSize="24">{n.detail}</text>
      </g>;})}
    </svg>
  </div></div>;
};

export const VRChatScene:React.FC<{duration?:number;ai?:ProductClip}> = ({duration=510,ai}) => {
  const f=useCurrentFrame();
  const closeFrames=83;
  const introFrames=Math.max(0,duration-(ai?.frames??185)-closeFrames);
  const secondFrom=introFrames+(ai?.frames??185);
  const width=1280,height=747;
  return <CinematicStage>
    <div style={{position:'absolute',top:77,width:'100%',textAlign:'center',fontSize:42,lineHeight:1.2,letterSpacing:-1.2,fontWeight:550}}><MotionWords text="Bring generated movement"/><span style={{color:C.rose}}> <MotionWords text="into VRChat." start={20}/></span></div>
    {f<introFrames&&<TrackingIntro duration={introFrames}/>}
    {ai&&<Sequence from={introFrames} durationInFrames={ai.frames} layout="none">
      <div style={{position:'absolute',left:(1920-width)/2,top:152,width,height}}>
        <CinematicClipCard src={ai.src} poster={ai.poster??''} sourceFrames={ai.frames} width={width} height={height} radius={18}/>
      </div>
    </Sequence>}
    <Sequence from={secondFrom} durationInFrames={closeFrames} layout="none">
      <div style={{position:'absolute',left:(1920-width)/2,top:152,width,height}}>
        <CinematicClipCard src="footage/vrchat-greeting-close.mp4" poster="captures/vrchat-greeting-close.png" sourceFrames={closeFrames} width={width} height={height} radius={18}/>
      </div>
    </Sequence>
    <div style={{position:'absolute',top:930,width:'100%',textAlign:'center',fontSize:24,color:C.silver}}>{f<introFrames?'Generated joint poses → virtual tracking → your avatar':'MotionCraft generation · VRChat playback · on-screen reply'}</div>
    <Chapter name="VRChat Studio" subtitle={f<introFrames?'How motion reaches the avatar':'Captured in VRChat'}/>
  </CinematicStage>;
};
