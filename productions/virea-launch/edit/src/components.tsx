import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {C,FONT,enter} from './theme';
import {MotionWords} from './SpatialLanguage';

export const Backdrop:React.FC<{children?:React.ReactNode;light?:boolean}> = ({children,light=false}) => <AbsoluteFill style={{background:light?'#eeeaee':C.bg,color:light?'#302d3a':C.ink,fontFamily:FONT,overflow:'hidden'}}>
  <AbsoluteFill style={{background:'radial-gradient(ellipse at 76% 30%, #bdb8d118, transparent 52%), radial-gradient(ellipse at 18% 95%, #c9adb810, transparent 40%)'}} />{children}
</AbsoluteFill>;
export const Kicker:React.FC<{children:React.ReactNode;color?:string}> = ({children,color=C.silver}) => <div style={{fontSize:23,fontWeight:600,letterSpacing:5,textTransform:'uppercase',color}}>{children}</div>;
export const Heading:React.FC<{eyebrow:string;title:string;sub?:string}> = ({eyebrow,title,sub}) => { const f=useCurrentFrame(); const p=enter(f,0,24);return <div style={{position:'absolute',left:96,top:72,opacity:p,transform:`translateY(${24*(1-p)}px)`}}><Kicker><MotionWords text={eyebrow}/></Kicker><h1 style={{fontSize:76,lineHeight:1.16,letterSpacing:-2.2,fontWeight:650,margin:'24px 0 16px'}}><MotionWords text={title} start={12}/></h1>{sub&&<div style={{fontSize:30,color:C.muted}}><MotionWords text={sub} start={32}/></div>}</div>;};
export const Pill:React.FC<{children:React.ReactNode;accent?:boolean}> = ({children,accent}) => <div style={{padding:'12px 22px',border:`1px solid ${accent?C.rose:C.line}`,borderRadius:30,background:accent?'#c9adb815':'#ffffff06',fontSize:24,color:accent?C.rose:C.silver}}>{children}</div>;
export const Moon:React.FC<{size?:number}> = ({size=44}) => <svg width={size} height={size} viewBox="0 0 100 100"><path d="M80 70A39 39 0 1 1 40 8A33 33 0 0 0 80 70Z" fill={C.silver}/><circle cx="76" cy="23" r="4" fill={C.rose}/></svg>;
