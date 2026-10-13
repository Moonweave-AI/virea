import React from 'react';
import {Freeze, Img, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {C} from './theme';

/**
 * An intact captured surface, not a reconstructed interface or a tiny crop.
 * Muted by construction; plays once. A declared source length holds its last
 * frame rather than repeating a model action or seeking beyond the source.
 */
export const CinematicClipCard: React.FC<{
  src?: string;
  poster: string;
  width?: number;
  height?: number;
  sourceFrames?: number;
  startFrom?: number;
  radius?: number;
  style?: React.CSSProperties;
}> = ({src, poster, width = 1920, height = 1080, sourceFrames, startFrom = 0, radius = 20, style}) => {
  const frame = useCurrentFrame();
  const localFrame = sourceFrames === undefined ? frame : Math.min(frame, Math.max(0, sourceFrames - startFrom - 1));
  const mediaStyle: React.CSSProperties = {position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', display: 'block'};
  return <div style={{position: 'relative', width, height, borderRadius: radius, transformStyle: 'preserve-3d', backfaceVisibility: 'hidden', ...style}}>
    <div style={{position: 'absolute', inset: 0, borderRadius: radius, overflow: 'hidden', background: C.bg, boxShadow: '0 32px 90px #03040b55, 0 6px 20px #00000035'}}>
      <Img src={staticFile(poster)} style={mediaStyle} />
      {src && <Freeze frame={localFrame}><OffthreadVideo src={staticFile(src)} trimBefore={startFrom} muted style={mediaStyle} /></Freeze>}
    </div>
    <div style={{position: 'absolute', inset: 0, borderRadius: radius, pointerEvents: 'none', border: '1px solid #bdb8d142', boxShadow: 'inset 0 1px 0 #f2edf125'}} />
  </div>;
};
