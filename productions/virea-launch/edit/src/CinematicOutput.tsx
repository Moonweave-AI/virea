import React from 'react';
import {AbsoluteFill, useVideoConfig} from 'remotion';
import {VireaFilm} from './Composition';
import {C} from './theme';

export const LOGICAL_WIDTH = 1920;
export const LOGICAL_HEIGHT = 1080;
export const MASTER_WIDTH = 3840;
export const MASTER_HEIGHT = 2160;

/** Keep editorial coordinates fixed; let Chromium rasterize text and UI at output density. */
export const CinematicOutput: React.FC<React.PropsWithChildren> = ({children}) => {
  const {width, height} = useVideoConfig();
  const zoom = Math.min(width / LOGICAL_WIDTH, height / LOGICAL_HEIGHT);
  return <AbsoluteFill style={{background: C.bg, overflow: 'hidden'}}>
    <div style={{
      position: 'absolute',
      left: (width - LOGICAL_WIDTH * zoom) / 2,
      top: (height - LOGICAL_HEIGHT * zoom) / 2,
      width: LOGICAL_WIDTH * zoom,
      height: LOGICAL_HEIGHT * zoom,
    }}>
      <div style={{position: 'relative', width: LOGICAL_WIDTH, height: LOGICAL_HEIGHT, zoom, overflow: 'hidden'}}>
        {children}
      </div>
    </div>
  </AbsoluteFill>;
};

export const VireaFilmOutput: React.FC<React.ComponentProps<typeof VireaFilm>> = (props) =>
  <CinematicOutput><VireaFilm {...props} /></CinematicOutput>;
