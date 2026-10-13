import { Easing, interpolate } from 'remotion';

export const C = { bg:'#151722', surface:'#20212d', ink:'#f2edf1', silver:'#bdb8d1', rose:'#c9adb8', muted:'#b0a8ba', line:'#41404f', green:'#9ac4ad' };
export const FONT = 'Inter, "Microsoft YaHei", sans-serif';
export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const enter = (f:number, start=0, length=24) => interpolate(f,[start,start+length],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:ease});
export const clamp = (f:number,a:number,b:number,x=0,y=1) => interpolate(f,[a,b],[x,y],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
