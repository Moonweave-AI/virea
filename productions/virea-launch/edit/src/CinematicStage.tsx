import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, FONT} from './theme';

/** A fixed, quiet lighting environment. Camera movement belongs to PageCam. */
export const CinematicStage: React.FC<{
  children: React.ReactNode;
  floor?: boolean;
  light?: number;
}> = ({children, floor = true, light = 1}) => <AbsoluteFill style={{background: '#11121b', color: C.ink, fontFamily: FONT, overflow: 'hidden'}}>
  <AbsoluteFill style={{
    opacity: light,
    background: 'radial-gradient(ellipse 1080px 560px at 67% 37%, #bdb8d119, transparent 78%), radial-gradient(ellipse 1100px 600px at 14% 90%, #c9adb812, transparent 78%)',
  }} />
  {floor && <div style={{position: 'absolute', left: -960, width: 3840, top: 760, height: 1700, transformOrigin: '50% 0', transform: 'perspective(1800px) rotateX(76deg)',
    background: 'linear-gradient(180deg, #bdb8d10d, transparent 50%), repeating-linear-gradient(90deg, transparent 0 239px, #bdb8d106 239px 240px)',
    borderTop: '1px solid #bdb8d120', opacity: 0.7,
  }} />}
  {children}
  <AbsoluteFill style={{pointerEvents: 'none', background: 'radial-gradient(ellipse at 50% 48%, transparent 53%, #090a1150 100%)'}} />
</AbsoluteFill>;
