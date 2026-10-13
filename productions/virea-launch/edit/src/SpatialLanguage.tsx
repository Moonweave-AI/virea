import React from 'react';
import {AbsoluteFill, Easing, Freeze, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C} from './theme';
import {ASSETS} from './Assets';
import {CinematicClipCard} from './CinematicClipCard';

const ease=Easing.bezier(.33,0,.15,1);
export const travel=(f:number,a:number,b:number,x=0,y=1)=>interpolate(f,[a,b],[x,y],{easing:ease,extrapolateLeft:'clamp',extrapolateRight:'clamp'});

/** Shotcraft blur-slide: opacity, depth and focus share one word-level curve. */
export const MotionWords:React.FC<{text:string;start?:number;frame?:number;style?:React.CSSProperties;accent?:string}>=({text,start=6,frame,style,accent})=>{
  const local=useCurrentFrame();const f=frame??local;
  return <span style={{display:'inline',perspective:1200,...style}}>{text.split(' ').map((word,i)=>{
    const p=travel(f,start+i*3,start+i*3+26);
    return <React.Fragment key={i}>{i?' ':''}<span style={{display:'inline-block',opacity:p,color:word===accent?C.rose:undefined,transform:`translateY(${30*(1-p)}px) rotateX(${38*(1-p)}deg)`,filter:p<.999?`blur(${8*(1-p)}px)`:undefined,transformOrigin:'50% 100%'}}>{word}</span></React.Fragment>;
  })}</span>;
};

/** Dataviz landscape: pinhole projection, one trunk and eight tangent tributaries. */
export const MotionLandscape:React.FC<{frame:number}>=({frame:f})=>{
  const camZ=travel(f,0,170,0,780),camX=travel(f,0,170,-100,120);
  const point=(x:number,z:number)=>{const depth=z-camZ;return {x:960+1050*(x-camX)/depth,y:400+1050*220/depth,depth};};
  const curves=Array.from({length:9},(_,i)=>Array.from({length:80},(_,j)=>{
    const z=1000+j*100;const side=i===4?0:(i<4?-1:1);const offset=side*(200+Math.abs(i-4)*320)*Math.exp(-(z-1000)/1800);
    return point(210+offset+90*Math.sin(z/1400),z);
  }));
  return <AbsoluteFill style={{background:'radial-gradient(ellipse at 58% 38%,#363040,#11121c 60%)'}}>
    <svg width="1920" height="1080"><defs><filter id="land-glow"><feGaussianBlur stdDeviation="4"/></filter></defs>
      {curves.map((pts,i)=><g key={i}>{pts.slice(1).map((p,j)=>{const a=pts[j];const grow=travel(f,2+i*3,48+i*3);if(j/79>grow)return null;const pulse=.4+.6*Math.pow(Math.max(0,Math.cos((j/79*3-f*.016+i*.2)*Math.PI*2)),6);return <line key={j} x1={a.x} y1={a.y} x2={p.x} y2={p.y} stroke={i===4?C.rose:C.silver} strokeWidth={Math.min(8,2500/p.depth)*(i===4?1.5:1)} opacity={pulse*(1-j/100)} />;})}</g>)}
    </svg>
    {['LANGUAGE','VOICE','MOTION'].map((word,i)=>{const p=point([-530,180,850][i],1900+i*430);return <div key={word} style={{position:'absolute',left:p.x-85,top:p.y-56,opacity:travel(f,35+i*9,61+i*9),fontSize:20,letterSpacing:3,color:i===1?C.rose:C.silver,transform:`translateY(${25*(1-travel(f,35+i*9,61+i*9))}px)`}}>{word}<div style={{marginTop:14,width:1,height:31,background:C.silver}}/></div>;})}
  </AbsoluteFill>;
};

/** Carousel3D: an outward-facing ring, double-sided cards, fixed shallow camera. */
export const StudioRing:React.FC<{duration:number}>=({duration})=>{
  const f=useCurrentFrame();const step=(duration-24)/5;const k=Math.max(0,(f-12)/step);const n=Math.floor(k);const part=k-n;
  const turn=(n+travel(part,0.36,1))*60;
  const cards=[
    {name:'Motion Lab',sub:'PRISM · describe a movement',...ASSETS.prism},
    {name:'Character Studio',sub:'A character you can talk to',...ASSETS.characterClip},
    {name:'VRChat Studio',sub:'Meet in a shared world',...ASSETS.ai},
    {name:'Set Up',sub:'Your device. Your models.',poster:ASSETS.setupDevice},
    {name:'Motion Lab',sub:'SentiAvatar · move with speech',...ASSETS.senti},
    {name:'One connected workflow',sub:'Verify. Create. Interact.',poster:ASSETS.setupVerification},
  ];
  return <AbsoluteFill style={{perspective:2400,perspectiveOrigin:'50% 47%'}}>
    <div style={{position:'absolute',left:960,top:485,transformStyle:'preserve-3d',transform:'translateZ(-1100px) rotateX(-10deg)'}}>
      <div style={{position:'absolute',left:-1300,top:-880,width:2600,height:2600,borderRadius:'50%',border:'1px solid #bdb8d124',background:'radial-gradient(ellipse,#c9adb816,transparent 66%)',transform:'rotateX(90deg)'}}/>
      <div style={{transformStyle:'preserve-3d',transform:`rotateY(${-turn}deg)`}}>{cards.map((card,i)=>{
        const angle=((i*60-turn+540)%360)-180;const depth=(1-Math.cos(angle*Math.PI/180))/2;
        const face:React.CSSProperties={position:'absolute',inset:0,backfaceVisibility:'hidden',WebkitBackfaceVisibility:'hidden',borderRadius:20,background:C.bg,border:'1px solid #bdb8d15c',boxShadow:'0 24px 70px #0008',overflow:'hidden'};
        const body=<><Freeze frame={Math.max(0,f-30)}><CinematicClipCard {...card} src={'src' in card?card.src:undefined} sourceFrames={'frames' in card?card.frames:undefined} width={780} height={439} radius={18}/></Freeze><div style={{padding:'26px 30px',fontSize:33,fontWeight:550}}>{card.name}<div style={{fontSize:21,color:C.silver,marginTop:12}}>{card.sub}</div></div><AbsoluteFill style={{background:C.bg,opacity:depth*.6}}/></>;
        return <div key={i} style={{position:'absolute',left:-390,top:-290,width:780,height:580,transformStyle:'preserve-3d',transform:`rotateY(${i*60}deg) translateZ(${1100+30*Math.max(0,1-Math.abs(angle)/30)}px)`}}><div style={face}>{body}</div><div style={{...face,transform:'rotateY(180deg)'}}>{body}</div></div>;
      })}</div>
    </div>
  </AbsoluteFill>;
};

/** Fixed -60° camera; complete panels glide along their own surface axis. */
export const SideGlide:React.FC<{frame:number;posters:string[]}>=({frame:f,posters})=><AbsoluteFill style={{perspective:1400,perspectiveOrigin:'30% 58%'}}>
  <div style={{position:'absolute',left:650,top:150,transform:'rotateY(-60deg) rotateZ(-2deg)',transformOrigin:'left top',transformStyle:'preserve-3d'}}>
    <div style={{display:'flex',gap:80,transform:`translateX(${travel(f,0,68,100,-1850)}px)`,transformStyle:'preserve-3d'}}>{posters.map((poster,i)=><div key={poster} style={{position:'relative',width:1560,height:878,flexShrink:0,boxShadow:'0 40px 100px #0009'}}><Img src={staticFile(poster)} style={{width:'100%',height:'100%',objectFit:'contain',borderRadius:18}}/><div style={{position:'absolute',top:24,left:34,fontSize:24,opacity:travel(f,i*12,i*12+25),transform:`translateZ(${140*(1-travel(f,i*12,i*12+30))}px)`,color:C.silver}}/></div>)}</div>
  </div>
</AbsoluteFill>;
