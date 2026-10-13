import {AudioSegment, CaptionUnit, MusicBed, MUSIC_CUE, SCENE_PROPS, SFX_CUES, SilverWipe, WIPE_CUES} from './Composition';
import {CinematicOutput, MASTER_HEIGHT, MASTER_WIDTH, VireaFilmOutput} from './CinematicOutput';
import {CAPTIONS, NARRATION} from './audio-data';
import {C} from './theme';
import {FPS, SHOTS, TOTAL} from './timeline';
import {OpeningScene, BrandScene, ClosingScene} from './scenes/BrandScenes';
import {FoundationScene} from './scenes/FoundationScene';
import {TimingScene} from './scenes/TimingScene';
import {ArchitectureScene} from './scenes/ArchitectureScene';
import {ModelsScene, CharacterScene, VRChatScene, SetupScene} from './scenes/ProductScenes';

const captionSchema = [{type: 'textarea', key: 'text', label: 'Caption', default: ''}];
const audioSchema = [{type: 'slider', key: 'volume', label: 'Volume', default: 1, min: 0, max: 1, step: 0.01}];
/** Component audio clips retain fades; the workbench's native audio arrays only support constant volume. */
export const WORKBENCH_AUDIO = {bgm: [MUSIC_CUE], sfx: SFX_CUES, narration: NARRATION};
export const WORKBENCH = {
  name: 'VIREA · Bring your avatars to life · English', fps: FPS, width: 1920, height: 1080, total: TOTAL, background: C.bg,
  outputWrapper: CinematicOutput, master: {width: MASTER_WIDTH, height: MASTER_HEIGHT},
  shots: [
    {...SHOTS[0], component: OpeningScene, props: {duration: SHOTS[0].duration}, durationProp: 'duration'},
    {...SHOTS[1], component: BrandScene, props: {duration: SHOTS[1].duration}, durationProp: 'duration'},
    {...SHOTS[2], component: ModelsScene, props: {duration: SHOTS[2].duration, ...SCENE_PROPS.motion}, durationProp: 'duration'},
    {...SHOTS[3], component: FoundationScene, props: {duration: SHOTS[3].duration}, durationProp: 'duration'},
    {...SHOTS[4], component: TimingScene, props: {duration: SHOTS[4].duration}, durationProp: 'duration'},
    {...SHOTS[5], component: CharacterScene, props: {duration: SHOTS[5].duration, ...SCENE_PROPS.character}, durationProp: 'duration', schema: [{type: 'text', key: 'videoSrc', label: 'Fresh character recording', default: SCENE_PROPS.character.videoSrc}]},
    {...SHOTS[6], component: VRChatScene, props: {duration: SHOTS[6].duration, ...SCENE_PROPS.vrchat}, durationProp: 'duration'},
    {...SHOTS[7], component: SetupScene, props: {duration: SHOTS[7].duration, ...SCENE_PROPS.setup}, durationProp: 'duration'},
    {...SHOTS[8], component: ArchitectureScene, props: {duration: SHOTS[8].duration}, durationProp: 'duration'},
    {...SHOTS[9], component: ClosingScene, props: {duration: SHOTS[9].duration}, durationProp: 'duration'},
  ],
  transitions: WIPE_CUES.map((cue) => ({...cue, component: SilverWipe, props: {duration: cue.duration}, durationProp: 'duration', cardId: 'silver-wipe', label: 'Silver orbital wipe'})),
  captions: CAPTIONS.map((cue) => ({...cue, label: cue.text, component: CaptionUnit, props: {text: cue.text, duration: cue.duration}, durationProp: 'duration', cardId: 'english-caption', schema: captionSchema})),
  overlays: [
    {id: 'music', from: MUSIC_CUE.from, duration: TOTAL, label: 'BGM · lunar ambient', component: MusicBed, props: {src: MUSIC_CUE.src, duration: TOTAL, volume: MUSIC_CUE.volume}, durationProp: 'duration', schema: audioSchema, cardId: 'music-bed'},
    ...NARRATION.map((cue) => ({id: `voice-${cue.id}`, from: cue.from, duration: cue.duration, label: `Narration · ${cue.id}`, component: AudioSegment, props: {src: cue.src, duration: cue.duration, volume: 1}, durationProp: 'duration', schema: audioSchema, cardId: 'narration'})),
    ...SFX_CUES.map((cue) => ({id: `sfx-${cue.id}`, from: cue.from, duration: cue.duration, label: `SFX · ${cue.id}`, component: AudioSegment, props: {src: cue.src, duration: cue.duration, volume: cue.volume}, durationProp: 'duration', schema: audioSchema, cardId: 'sound-effect'})),
  ],
  sfx: [], bgm: [], order: ['captions', 'transitions', 'overlays'], original: VireaFilmOutput,
};
