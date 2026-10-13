import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Backdrop, Heading} from '../components';
import {C, FONT, clamp, enter} from '../theme';
import {CinematicPageCam} from '../CinematicPageCam';
import {MotionWords} from '../SpatialLanguage';

const TRACK_X = 324;
const TRACK_WIDTH = 1464;
const at = (seconds: number) => TRACK_X + (seconds / 24) * TRACK_WIDTH;

const MotionClip: React.FC<{
  frame: number;
  reveal: number;
  start: number;
  end: number;
  title: string;
  translation: string;
  number: string;
}> = ({frame, reveal, start, end, title, translation, number}) => {
  const p = enter(frame, reveal, 25);
  return (
    <div
      style={{
        position: 'absolute',
        left: at(start),
        top: 427,
        width: at(end) - at(start) - 8,
        height: 100,
        border: '1px solid #bdb8d15c',
        borderRadius: 14,
        background: 'linear-gradient(120deg, #bdb8d12d, #bdb8d114)',
        boxSizing: 'border-box',
        padding: '16px 20px',
        opacity: p,
        translate: `0 ${12 * (1 - p)}px`,
      }}
    >
      <div style={{fontSize: 30, lineHeight: 1.2, fontWeight: 600, letterSpacing: -0.4}}>{title}</div>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 11, fontSize: 22, color: C.silver}}>
        <span>{translation}</span><span style={{fontSize: 17, letterSpacing: 2, opacity: 0.65}}>{number}</span>
      </div>
    </div>
  );
};

/** A conceptual, independently timed motion/speech score — not a test recording. */
export const TimingScene: React.FC<{duration?: number}> = ({duration = 450}) => {
  const frame = useCurrentFrame();
  const f = (frame * 450) / Math.max(1, duration);
  const shell = enter(f, 14, 27);
  const playhead = clamp(f, 88, 394, 0, 24);
  const playX = at(playhead);
  const voice = enter(f, 59, 25);
  const isSpeaking = playhead >= 8 && playhead <= 14;
  const clock = `${Math.floor(playhead).toString().padStart(2, '0')}.${Math.floor((playhead % 1) * 10)}`;

  return <Backdrop>
    <Heading eyebrow="Independent tracks" title="Motion and speech, on their own time." sub="Longer actions. Speech exactly where it belongs." />

    <div style={{position: 'absolute', right: 96, top: 75, border: `1px solid ${C.line}`, borderRadius: 24, padding: '10px 20px', fontSize: 21, color: C.muted, opacity: enter(f, 12, 20)}}>Concept illustration</div>

    <CinematicPageCam frame={f} keys={[
      {frame:0,cx:1080,cy:590,zoom:.68,rotX:52,rotY:-24},
      {frame:75,cx:960,cy:540,zoom:1,rotX:0,rotY:0},
      {frame:450,cx:960,cy:540,zoom:1,rotX:0,rotY:0},
    ]}>
    <div style={{position: 'absolute', left: 96, top: 326, width: 1728, height: 373, border: `1px solid ${C.line}`, background: 'linear-gradient(140deg, #20212ded, #20212d80)', borderRadius: 24, opacity: shell, boxShadow: '0 22px 60px #00000018'}} />

    <div style={{opacity: shell}}>
      <div style={{position: 'absolute', left: 128, top: 364, fontSize: 17, color: C.muted, letterSpacing: 3}}>TIMELINE</div>
      {[0, 4, 8, 12, 16, 20, 24].map((second) => <React.Fragment key={second}>
        <div style={{position: 'absolute', left: at(second) - (second === 24 ? 33 : 0), top: 361, fontSize: 21, color: C.muted, fontVariantNumeric: 'tabular-nums'}}>{second.toString().padStart(2, '0')}s</div>
        <div style={{position: 'absolute', left: at(second), top: 401, height: 246, width: 1, background: second === 0 || second === 24 ? '#bdb8d124' : '#bdb8d114'}} />
      </React.Fragment>)}
      <div style={{position: 'absolute', left: 131, top: 452, fontSize: 32, fontWeight: 600}}>Motion</div>
      <div style={{position: 'absolute', left: 131, top: 495, fontSize: 21, color: C.silver}}>24 seconds</div>
      <div style={{position: 'absolute', left: 131, top: 568, fontSize: 32, fontWeight: 600, color: C.rose}}>Speech</div>
      <div style={{position: 'absolute', left: 131, top: 610, fontSize: 21, color: C.rose, opacity: 0.8}}>6 seconds</div>
      <div style={{position: 'absolute', left: TRACK_X, top: 603, width: TRACK_WIDTH, borderTop: '1px dashed #c9adb82b'}} />
    </div>

    <MotionClip frame={f} reveal={27} start={0} end={6} title="Walk forward" translation="0–6 seconds" number="01" />
    <MotionClip frame={f} reveal={35} start={6} end={11} title="Wave hello" translation="6–11 seconds" number="02" />
    <MotionClip frame={f} reveal={43} start={11} end={17} title="Turn left" translation="11–17 seconds" number="03" />
    <MotionClip frame={f} reveal={51} start={17} end={24} title="Look around" translation="17–24 seconds" number="04" />

    <div style={{position: 'absolute', left: at(8), top: 562, width: at(14) - at(8), height: 80, borderRadius: 14, background: isSpeaking ? '#c9adb836' : '#c9adb824', border: '1px solid #c9adb875', boxSizing: 'border-box', opacity: voice, translate: `0 ${12 * (1 - voice)}px`, overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: 18, top: 10, fontSize: 22, color: C.rose}}>Hello. Good to see you.</div>
      <svg width="100%" height="33" viewBox="0 0 365 33" style={{position: 'absolute', top: 37, left: 0}}>
        {Array.from({length: 53}, (_, i) => {
          const amplitude = 4 + 20 * Math.abs(Math.sin(i * 1.77) * Math.cos(i * 0.38));
          const x = 20 + i * 6.2;
          return <rect key={i} x={x} y={(33 - amplitude) / 2} width={2.6} height={amplitude} rx={1.3} fill={C.rose} opacity={0.48 + 0.5 * (Math.sin(i * 0.72) ** 2)} />;
        })}
      </svg>
    </div>

    <div style={{position: 'absolute', left: playX, top: 399, height: 251, width: 2, background: C.ink, boxShadow: '0 0 17px #f2edf150', opacity: enter(f, 80, 14)}}>
      <div style={{position: 'absolute', top: -7, left: -5, width: 12, height: 12, borderRadius: 4, background: C.ink, rotate: '45deg'}} />
      <div style={{position: 'absolute', top: 261, left: playhead > 22 ? -58 : -25, fontSize: 18, color: C.ink, fontFamily: FONT, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap'}}>{clock}s</div>
    </div>

    <div style={{position: 'absolute', left: 96, top: 778, width: 1728, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 25, opacity: enter(f, 267, 28), translate: `0 ${16 * (1 - enter(f, 267, 28))}px`}}>
      <span style={{fontSize: 43, letterSpacing: -1.1, color: C.rose}}><MotionWords text="Speech ends." frame={f} start={267}/></span>
      <svg width="38" height="24" viewBox="0 0 38 24"><path d="M1 12h32M24 3l10 9-10 9" fill="none" stroke={C.silver} strokeWidth="1.8" /></svg>
      <span style={{fontSize: 43, letterSpacing: -1.1, color: C.ink}}><MotionWords text="Motion continues." frame={f} start={282}/></span>
    </div>
    </CinematicPageCam>
  </Backdrop>;
};
