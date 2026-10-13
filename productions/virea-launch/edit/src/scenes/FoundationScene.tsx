import React from 'react';
import {useCurrentFrame} from 'remotion';
import {CinematicStage} from '../CinematicStage';
import {CinematicPageCam} from '../CinematicPageCam';
import {C, clamp, enter} from '../theme';
import {MotionWords} from '../SpatialLanguage';

type Point = [number, number];
const joints: Record<string, Point> = {
  head: [210, 40], neck: [210, 87], chest: [210, 138], spine: [210, 180], hips: [210, 224],
  leftShoulder: [166, 103], leftElbow: [117, 171], leftWrist: [82, 245], leftHand: [72, 268],
  rightShoulder: [254, 103], rightElbow: [303, 171], rightWrist: [338, 245], rightHand: [348, 268],
  leftHip: [177, 230], leftKnee: [169, 336], leftAnkle: [157, 449], leftToe: [139, 466],
  rightHip: [243, 230], rightKnee: [251, 336], rightAnkle: [263, 449], rightToe: [281, 466],
};
const bones = [
  ['head', 'neck'], ['neck', 'chest'], ['chest', 'spine'], ['spine', 'hips'],
  ['neck', 'leftShoulder'], ['leftShoulder', 'leftElbow'], ['leftElbow', 'leftWrist'], ['leftWrist', 'leftHand'],
  ['neck', 'rightShoulder'], ['rightShoulder', 'rightElbow'], ['rightElbow', 'rightWrist'], ['rightWrist', 'rightHand'],
  ['hips', 'leftHip'], ['leftHip', 'leftKnee'], ['leftKnee', 'leftAnkle'], ['leftAnkle', 'leftToe'],
  ['hips', 'rightHip'], ['rightHip', 'rightKnee'], ['rightKnee', 'rightAnkle'], ['rightAnkle', 'rightToe'],
];

const Axes: React.FC<{x: number; y: number; angle?: number; scale?: number}> = ({x, y, angle = 0, scale = 1}) => {
  // Project one orthonormal basis, rather than rotating three arbitrary arrows.
  const yaw = angle * Math.PI / 180;
  const pitch = -0.42;
  const basis = [
    {label: 'x', v: [Math.cos(yaw), 0, -Math.sin(yaw)], color: C.silver},
    {label: 'y', v: [0, 1, 0], color: C.rose},
    {label: 'z', v: [Math.sin(yaw), 0, Math.cos(yaw)], color: C.muted},
  ];
  return <g transform={`translate(${x} ${y}) scale(${scale})`}>{basis.map(({label, v, color}) => {
    const px = v[0] * 63;
    const py = (-v[1] * Math.cos(pitch) + v[2] * Math.sin(pitch)) * 63;
    const direction = Math.atan2(py, px) * 180 / Math.PI;
    return <g key={label}><line x1={0} y1={0} x2={px} y2={py} stroke={color} strokeWidth={1.9} /><path d="M-8 -4L0 0-8 4" transform={`translate(${px} ${py}) rotate(${direction})`} stroke={color} fill="none" strokeWidth={1.9} /><text x={px * 1.2 - 4} y={py * 1.2 + 4} fill={color} fontSize={17}>{label}</text></g>;
  })}</g>;
};

const Skeleton: React.FC<{target?: boolean; yaw?: number}> = ({target = false, yaw = 0}) => {
  // Two fixed explanatory rest skeletons, never a generated-motion sample.
  const point = (name: string): Point => {
    const [x, y] = joints[name];
    const localX = (x - 210) * (target ? 0.86 : 1);
    const localY = target && y > 224 ? 224 + (y - 224) * 1.03 : y;
    const depth = /Knee/.test(name) ? 28 : /Elbow|Wrist|Hand/.test(name) ? -18 : /Toe/.test(name) ? 38 : 0;
    const angle = yaw * Math.PI / 180;
    const rotatedX = localX * Math.cos(angle) + depth * Math.sin(angle);
    const rotatedZ = -localX * Math.sin(angle) + depth * Math.cos(angle);
    const perspective = 850 / (850 + rotatedZ);
    return [210 + rotatedX * perspective, 224 + (localY - 224) * perspective];
  };
  return <svg width="420" height="510" viewBox="0 0 420 510">
    <ellipse cx="210" cy="485" rx="120" ry="15" fill="#bdb8d108" stroke="#bdb8d11d" />
    <line x1="210" y1="15" x2="210" y2="476" stroke="#bdb8d10d" strokeDasharray="4 8" />
    {bones.map(([from, to]) => {
      const a = point(from); const b = point(to);
      return <g key={`${from}-${to}`}>
        <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.silver} strokeOpacity="0.1" strokeWidth="11" strokeLinecap="round" />
        <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.silver} strokeWidth="3" strokeLinecap="round" />
      </g>;
    })}
    {Object.keys(joints).map((name) => {
      const p = point(name);
      return <circle key={name} cx={p[0]} cy={p[1]} r={name === 'hips' ? 8 : name === 'head' ? 18 : 4.6} fill={name === 'head' ? C.bg : name === 'hips' ? C.rose : C.ink} stroke={name === 'head' ? C.silver : C.surface} strokeWidth={name === 'head' ? 2 : 1.5} />;
    })}
    <Axes x={point('hips')[0]} y={point('hips')[1]} angle={(target ? -25 : 15) + yaw} scale={0.88} />
    <circle cx={point('leftWrist')[0]} cy={point('leftWrist')[1]} r="15" fill="none" stroke={C.rose} strokeOpacity="0.7" strokeWidth="1" />
    <circle cx={point('rightAnkle')[0]} cy={point('rightAnkle')[1]} r="15" fill="none" stroke={C.rose} strokeOpacity="0.7" strokeWidth="1" />
  </svg>;
};

export const FoundationScene: React.FC<{duration?: number}> = ({duration = 360}) => {
  const frame = useCurrentFrame();
  const f = (frame * 360) / Math.max(1, duration);
  const turn = clamp(f, 74, 205, -55, 35);
  const left = enter(f, 15, 26);
  const center = enter(f, 43, 26);
  const right = enter(f, 104, 26);
  return <CinematicStage>
    <div style={{position: 'absolute', left: 96, top: 64, fontSize: 20, letterSpacing: 3, color: C.silver}}><MotionWords text="ONE MOTION FOUNDATION"/></div>
    <div style={{position: 'absolute', left: 96, top: 110, fontSize: 57, letterSpacing: -1.7, fontWeight: 550}}><MotionWords text="One motion. Many skeletons." start={16}/></div>
    <div style={{position: 'absolute', right: 96, top: 75, fontSize: 20, color: C.muted}}>Concept illustration</div>
    <CinematicPageCam frame={f} keys={[
      {frame: 0, cx: 1080, cy: 560, zoom: 0.6, rotX: 24, rotY: -48},
      {frame: 65, cx: 960, cy: 535, zoom: 0.9, rotX: 5, rotY: -12},
      {frame: 115, cx: 900, cy: 550, zoom: 0.99, rotX: 2, rotY: -2},
      {frame: 223, cx: 1020, cy: 550, zoom: 0.99, rotX: 2, rotY: 2},
      {frame: 323, cx: 960, cy: 550, zoom: 0.91, rotX: 0, rotY: 0},
      {frame: 360, cx: 960, cy: 550, zoom: 0.91, rotX: 0, rotY: 0},
    ]}>
    <div style={{position: 'absolute', left: 123, top: 282, opacity: left, transform: `translate3d(0, ${22 * (1 - left)}px, 18px)`}}><Skeleton yaw={clamp(f, 18, 198, -16, 17)} /></div>
    <div style={{position: 'absolute', left: 1377, top: 282, opacity: right, transform: `translate3d(0, ${22 * (1 - right)}px, 18px)`}}><Skeleton target yaw={clamp(f, 104, 283, -16, 17)} /></div>

    <svg width="1920" height="900" style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none'}}>
      <path d="M540 532C610 532 633 471 720 471" fill="none" stroke={C.line} strokeWidth="2" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - enter(f, 48, 40)} />
      <path d="M1200 471C1287 471 1310 532 1380 532" fill="none" stroke={C.line} strokeWidth="2" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - enter(f, 108, 40)} />
      <path d="M709 465l11 6-11 6" fill="none" stroke={C.silver} strokeWidth="1.7" opacity={enter(f, 78, 16)} />
      <path d="M1369 526l11 6-11 6" fill="none" stroke={C.silver} strokeWidth="1.7" opacity={enter(f, 135, 16)} />
      <g style={{opacity: center}}>
        <ellipse cx="960" cy="466" rx="145" ry="54" fill="none" stroke="#bdb8d127" />
        <ellipse cx="960" cy="466" rx="80" ry="111" fill="none" stroke="#bdb8d120" transform="rotate(-24 960 466)" />
        <circle cx="960" cy="466" r="112" fill="#bdb8d107" stroke="#bdb8d12b" />
        <circle cx="960" cy="466" r="5" fill={C.ink} />
        <Axes x={960} y={466} angle={turn} scale={1.65} />
      </g>
      <circle cx={clamp(f, 66, 104, 540, 718)} cy={532 - 61 * clamp(f, 66, 104)} r="4" fill={C.silver} opacity={enter(f, 60, 10) * (1 - enter(f, 100, 12))} />
      <circle cx={clamp(f, 131, 169, 1200, 1380)} cy={471 + 61 * clamp(f, 131, 169)} r="4" fill={C.rose} opacity={enter(f, 125, 10) * (1 - enter(f, 165, 12))} />
    </svg>

    <div style={{position: 'absolute', left: 617, top: 612, width: 686, textAlign: 'center', opacity: enter(f, 88, 26)}}>
      <div style={{fontSize: 23, letterSpacing: 2, color: C.muted, marginBottom: 18}}>Basis change</div>
      <div style={{fontFamily: 'Georgia, serif', fontSize: 47, color: C.ink, letterSpacing: 1}}>
        <i>R</i><sub style={{fontSize: 21}}>target</sub> = <i>C R</i><sub style={{fontSize: 21}}>source</sub><i> C</i><sup style={{fontSize: 25}}>−1</sup>
      </div>
      <div style={{marginTop: 34, paddingTop: 23, borderTop: `1px solid ${C.line}`, fontSize: 27, color: C.silver}}>Bind pose · Hierarchy · Proportions</div>
      <div style={{marginTop: 13, fontSize: 22, color: C.muted}}>Retargeting respects each joint’s rest orientation.</div>
    </div>
    <div style={{position: 'absolute', left: 123, top: 801, width: 420, textAlign: 'center', opacity: left}}>
      <div style={{fontSize: 34, fontWeight: 600}}>Source skeleton</div><div style={{fontSize: 23, color: C.muted, marginTop: 11}}>Positions · Rotations · Hierarchy</div>
    </div>
    <div style={{position: 'absolute', left: 1377, top: 801, width: 420, textAlign: 'center', opacity: right}}>
      <div style={{fontSize: 34, fontWeight: 600}}>Target skeleton</div><div style={{fontSize: 23, color: C.muted, marginTop: 11}}>VRM Humanoid</div>
    </div>
    </CinematicPageCam>
  </CinematicStage>;
};
