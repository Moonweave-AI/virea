export const FPS=30;
export const SHOTS = [
  {id:'opening', from:0, duration:255, label:'From avatars to agents', narration:'VIREA brings your existing avatars to life through language, voice, and generated movement.'},
  {id:'brand', from:255, duration:330, label:'Three connected studios', narration:'Explore generated motion, bring your own character to life, and take the interaction into a shared virtual world, all through one connected workflow.'},
  {id:'motion', from:585, duration:450, label:'Motion Lab', narration:'Start in Motion Lab. Describe a movement with PRISM, or create expressive gestures from speech with SentiAvatar. Watch the original skeleton and the retargeted character side by side.'},
  {id:'retarget', from:1035, duration:375, label:'Motion foundation', narration:'VIREA carries motion between different skeletons by resolving their coordinate systems, joint hierarchies, and rest poses, then adapting the result to your character.'},
  {id:'timeline', from:1410, duration:330, label:'Your own timing', narration:'Shape the performance on a shared timeline. Arrange movement and speech independently, so a gesture can begin before a word or linger after it.'},
  {id:'character', from:1740, duration:390, label:'Character Studio', narration:'In Character Studio, import your VRM and start a conversation. Your character responds through language and generated movement, while you follow the performance in the browser.'},
  {id:'vrchat', from:2130, duration:510, label:'VRChat Studio', narration:'That movement can continue inside VRChat. VIREA sends the generated pose through virtual tracking for the head, hands, body, and feet. Here, the character greets you in the world, with the reply displayed as subtitles.'},
  {id:'setup', from:2640, duration:420, label:'Set Up', narration:'Getting started happens in one place. Set Up checks your device, discovers local services, and connects your chosen models. Follow each deployment, then run a generation test to see the result.'},
  {id:'architecture', from:3060, duration:435, label:'One foundation', narration:'Standard interfaces bring language, speech, and motion models into the same runtime. A shared motion foundation connects them to the browser and VRChat, with execution records you can inspect.'},
  {id:'close', from:3495, duration:300, label:'Bring your avatars to life', narration:'Bring your models, choose your avatar, and create an interaction of your own. VIREA is open source. Bring your avatars to life.'},
] as const;
export const TOTAL=3795;
