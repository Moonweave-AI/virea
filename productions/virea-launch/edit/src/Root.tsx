import React from 'react';
import {Composition} from 'remotion';
import {z} from 'zod';
import {FILM_DEFAULTS, VireaFilm} from './Composition';
import {MASTER_HEIGHT, MASTER_WIDTH, VireaFilmOutput} from './CinematicOutput';
import {FPS, SHOTS, TOTAL} from './timeline';
import {OpeningScene, BrandScene, ClosingScene} from './scenes/BrandScenes';
import {FoundationScene} from './scenes/FoundationScene';
import {TimingScene} from './scenes/TimingScene';
import {ArchitectureScene} from './scenes/ArchitectureScene';

const schema = z.object({withMusic: z.boolean(), withNarration: z.boolean(), withSfx: z.boolean(), captions: z.boolean()});

export const RemotionRoot: React.FC = () => <>
  <Composition id="VIREA-English" component={VireaFilm} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} defaultProps={FILM_DEFAULTS} schema={schema} />
  <Composition id="VIREA-English-4K" component={VireaFilmOutput} durationInFrames={TOTAL} fps={FPS} width={MASTER_WIDTH} height={MASTER_HEIGHT} defaultProps={FILM_DEFAULTS} schema={schema} />
  <Composition id="Opening" component={OpeningScene} durationInFrames={SHOTS[0].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[0].duration}} />
  <Composition id="Brand" component={BrandScene} durationInFrames={SHOTS[1].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[1].duration}} />
  <Composition id="Foundation" component={FoundationScene} durationInFrames={SHOTS[3].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[3].duration}} />
  <Composition id="Timing" component={TimingScene} durationInFrames={SHOTS[4].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[4].duration}} />
  <Composition id="Architecture" component={ArchitectureScene} durationInFrames={SHOTS[8].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[8].duration}} />
  <Composition id="Closing" component={ClosingScene} durationInFrames={SHOTS[9].duration} fps={FPS} width={1920} height={1080} defaultProps={{duration: SHOTS[9].duration}} />
</>;
