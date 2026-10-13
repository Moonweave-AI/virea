import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

/** Logical 1920 × 1080 camera coordinates. Supply 2× source textures for 4K. */
export type CinematicCamKey = {
  frame: number;
  cx: number;
  cy: number;
  zoom: number;
  rotX?: number;
  rotY?: number;
  rotZ?: number;
  perspective?: number;
};

const travel = Easing.bezier(0.33, 0, 0.15, 1);

/**
 * PageCam's focal-point mathematics, adapted from video-shotcraft.
 * One progress curve owns translation, rotation and magnification. CSS layout
 * zoom keeps native 2× capture pixels sharp instead of enlarging a GPU layer.
 * Real-page shots establish the complete surface before a bounded push.
 */
export const CinematicPageCam: React.FC<{
  keys: readonly CinematicCamKey[];
  children: React.ReactNode;
  frame?: number;
  pageWidth?: number;
  pageHeight?: number;
  ease?: (progress: number) => number;
  maxZoom?: number;
}> = ({keys, children, frame: frameProp, pageWidth = 1920, pageHeight = 1080, ease = travel, maxZoom = 1.2}) => {
  const localFrame = useCurrentFrame();
  const frame = frameProp ?? localFrame;
  if (keys.length === 0) throw new Error('CinematicPageCam needs a camera key.');
  if (keys.some((key, index) => key.zoom <= 0 || key.zoom > maxZoom || (index > 0 && key.frame <= keys[index - 1].frame))) {
    throw new Error('Camera keys must increase in time and stay inside the source-resolution zoom budget.');
  }
  let a = keys[0];
  let b = a;
  for (let index = 1; index < keys.length; index++) {
    b = keys[index];
    if (frame <= b.frame) break;
    a = b;
  }
  const t = a.frame === b.frame ? 1 : interpolate(frame, [a.frame, b.frame], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease,
  });
  const mix = (from: number, to: number) => from + (to - from) * t;
  const cx = mix(a.cx, b.cx);
  const cy = mix(a.cy, b.cy);
  const zoom = mix(a.zoom, b.zoom);
  const rx = mix(a.rotX ?? 0, b.rotX ?? 0);
  const ry = mix(a.rotY ?? 0, b.rotY ?? 0);
  const rz = mix(a.rotZ ?? 0, b.rotZ ?? 0);
  const perspective = mix(a.perspective ?? 1800, b.perspective ?? 1800);
  return <AbsoluteFill style={{pointerEvents: 'none', overflow: 'hidden'}}>
    <AbsoluteFill style={{perspective: perspective * zoom, perspectiveOrigin: '960px 540px'}}>
      <div style={{
        position: 'absolute', width: pageWidth, height: pageHeight, zoom,
        transformOrigin: `${cx}px ${cy}px`, transformStyle: 'preserve-3d',
        transform: `translate(${960 / zoom - cx}px, ${540 / zoom - cy}px) rotateY(${ry}deg) rotateX(${rx}deg) rotateZ(${rz}deg)`,
      }}>{children}</div>
    </AbsoluteFill>
  </AbsoluteFill>;
};
