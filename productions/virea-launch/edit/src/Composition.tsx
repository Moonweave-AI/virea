import React from 'react';
import {Audio} from '@remotion/media';
import {loadFont} from '@remotion/google-fonts/Inter';
import {AbsoluteFill, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ASSETS} from './Assets';
import {CAPTIONS, NARRATION} from './audio-data';
import {C, clamp, enter} from './theme';
import {SHOTS, TOTAL} from './timeline';
import {OpeningScene, BrandScene, ClosingScene} from './scenes/BrandScenes';
import {FoundationScene} from './scenes/FoundationScene';
import {TimingScene} from './scenes/TimingScene';
import {ArchitectureScene} from './scenes/ArchitectureScene';
import {ModelsScene, CharacterScene, VRChatScene, SetupScene} from './scenes/ProductScenes';

export const {fontFamily: FILM_FONT} = loadFont('normal', {weights: ['400', '500', '600', '700'], subsets: ['latin']});
export type VireaFilmProps = {withMusic?: boolean; withNarration?: boolean; withSfx?: boolean; captions?: boolean};
export const FILM_DEFAULTS = {withMusic: true, withNarration: true, withSfx: true, captions: true};
export const SCENE_PROPS = {
  motion: {prism: ASSETS.prism, senti: ASSETS.senti},
  character: {videoSrc: ASSETS.characterClip.src, posterSrc: ASSETS.characterClip.poster, videoFrames: ASSETS.characterClip.frames},
  vrchat: {ai: ASSETS.ai},
  setup: {deviceCapture: ASSETS.setupDevice, deploymentCapture: ASSETS.setupDeployment, verificationCapture: ASSETS.setupVerification},
};
export const WIPE_CUES = SHOTS.slice(1).map((shot) => ({id: `wipe-${shot.id}`, from: shot.from - 14, duration: 28}));
export const SFX_CUES = [
  {id: 'brand-arrival', from: SHOTS[1].from - 8, duration: 90, src: 'audio/air-zoom-vacuum.mp3', volume: 0.1},
  {id: 'world-arrival', from: SHOTS[6].from - 8, duration: 90, src: 'audio/stardust-swish.mp3', volume: 0.09},
  {id: 'closing-arrival', from: SHOTS[9].from - 8, duration: 90, src: 'audio/stardust-swish.mp3', volume: 0.08},
];
export const MUSIC_CUE = {from: 0, duration: TOTAL, src: 'audio/music-arranged.wav', volume: 0.08};

export const SilverWipe: React.FC<{duration?: number}> = ({duration = 16}) => {
  const f = useCurrentFrame();
  const travel = clamp(f, 0, Math.max(1, duration - 1), -240, 2110);
  const opacity = Math.sin(Math.PI * clamp(f, 0, Math.max(1, duration - 1)));
  return <AbsoluteFill style={{pointerEvents: 'none', overflow: 'hidden'}}>
    <div style={{position:'absolute',left:travel-920,top:-750,width:2100,height:2500,borderRadius:'50%',border:'2px solid #c9adb869',boxShadow:'22px 0 75px #bdb8d124, inset -20px 0 65px #c9adb81a',transform:'rotateY(66deg) rotateZ(-27deg)',opacity:opacity*.8}}/>
    <div style={{position: 'absolute', left: travel, top: 0, height: '100%', width: 160, opacity, background: 'linear-gradient(90deg, transparent, #bdb8d132 49%, #c9adb82b 51%, transparent)', filter: 'blur(7px)'}} />
    <div style={{position: 'absolute', left: travel + 80, top: 0, height: '100%', width: 1, opacity: opacity * 0.42, background: C.silver}} />
  </AbsoluteFill>;
};

export const CaptionUnit: React.FC<{text?: string; duration?: number}> = ({text = '', duration = 90}) => {
  const f = useCurrentFrame();
  return <div style={{position: 'absolute', left: 0, right: 0, bottom: 8, display: 'flex', justifyContent: 'center', padding: '0 130px', boxSizing: 'border-box', pointerEvents: 'none', opacity: enter(f, 0, 4) * (1 - clamp(f, Math.max(4, duration - 4), duration))}}>
    <div style={{maxWidth: 1600, padding: '15px 27px', boxSizing: 'border-box', borderRadius: 13, background: '#090b14c2', border: '1px solid #f2edf11c', color: '#f6f3f6', fontFamily: FILM_FONT, fontSize: 39, fontWeight: 500, lineHeight: 1.22, letterSpacing: -0.3, textAlign: 'center', textWrap: 'balance'}}>{text}</div>
  </div>;
};

export const AudioSegment: React.FC<{src?: string; from?: number; duration?: number; volume?: number}> = ({src = '', from = 0, duration = 90, volume = 1}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const local = frame - from;
  const gain = clamp(local, 0, fps * 0.03) * clamp(local, duration - fps * 0.03, duration, 1, 0);
  return src ? <Audio src={staticFile(src)} from={from} durationInFrames={duration} volume={volume * gain} premountFor={fps} /> : null;
};

export const MusicBed: React.FC<{src?: string; duration?: number; volume?: number}> = ({src = MUSIC_CUE.src, duration = TOTAL, volume = MUSIC_CUE.volume}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <Audio src={staticFile(src)} durationInFrames={duration} volume={volume * clamp(frame, 0, 2 * fps) * clamp(frame, duration - 4 * fps, duration, 1, 0)} premountFor={fps} />;
};

export const VireaFilm: React.FC<VireaFilmProps> = ({withMusic = true, withNarration = true, withSfx = true, captions = true}) => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill style={{background: C.bg, fontFamily: FILM_FONT}}>
    <Sequence name="01 — Beyond words" from={SHOTS[0].from} durationInFrames={SHOTS[0].duration} premountFor={fps}><OpeningScene duration={SHOTS[0].duration} /></Sequence>
    <Sequence name="02 — VIREA" from={SHOTS[1].from} durationInFrames={SHOTS[1].duration} premountFor={fps}><BrandScene duration={SHOTS[1].duration} /></Sequence>
    <Sequence name="03 — Motion Lab" from={SHOTS[2].from} durationInFrames={SHOTS[2].duration} premountFor={fps}><ModelsScene duration={SHOTS[2].duration} {...SCENE_PROPS.motion} /></Sequence>
    <Sequence name="04 — Motion foundation" from={SHOTS[3].from} durationInFrames={SHOTS[3].duration} premountFor={fps}><FoundationScene duration={SHOTS[3].duration} /></Sequence>
    <Sequence name="05 — Independent timing" from={SHOTS[4].from} durationInFrames={SHOTS[4].duration} premountFor={fps}><TimingScene duration={SHOTS[4].duration} /></Sequence>
    <Sequence name="06 — Character Studio" from={SHOTS[5].from} durationInFrames={SHOTS[5].duration} premountFor={fps}><CharacterScene duration={SHOTS[5].duration} {...SCENE_PROPS.character} /></Sequence>
    <Sequence name="07 — VRChat Studio" from={SHOTS[6].from} durationInFrames={SHOTS[6].duration} premountFor={fps}><VRChatScene duration={SHOTS[6].duration} {...SCENE_PROPS.vrchat} /></Sequence>
    <Sequence name="08 — Set Up" from={SHOTS[7].from} durationInFrames={SHOTS[7].duration} premountFor={fps}><SetupScene duration={SHOTS[7].duration} {...SCENE_PROPS.setup} /></Sequence>
    <Sequence name="09 — Architecture" from={SHOTS[8].from} durationInFrames={SHOTS[8].duration} premountFor={fps}><ArchitectureScene duration={SHOTS[8].duration} /></Sequence>
    <Sequence name="10 — Start creating" from={SHOTS[9].from} durationInFrames={SHOTS[9].duration} premountFor={fps}><ClosingScene duration={SHOTS[9].duration} /></Sequence>
    {withMusic && <MusicBed />}
    {withNarration && NARRATION.map(cue => <AudioSegment key={cue.id} {...cue} />)}
    {withSfx && <><AudioSegment {...SFX_CUES[0]} /><AudioSegment {...SFX_CUES[1]} /><AudioSegment {...SFX_CUES[2]} /></>}
    {WIPE_CUES.map((cue) => <Sequence key={cue.id} name={cue.id} from={cue.from} durationInFrames={cue.duration} premountFor={fps}><SilverWipe duration={cue.duration} /></Sequence>)}
    {captions && CAPTIONS.map((cue) => <Sequence key={cue.id} name={cue.text} from={cue.from} durationInFrames={cue.duration} premountFor={fps}><CaptionUnit text={cue.text} duration={cue.duration} /></Sequence>)}
  </AbsoluteFill>;
};
