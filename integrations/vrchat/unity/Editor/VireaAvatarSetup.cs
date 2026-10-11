// Copy this Editor folder into an Avatars project created by VRChat Creator Companion.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;

namespace Virea.VRChat.Editor
{
    public sealed class VireaAvatarSetup : EditorWindow
    {
        VRCAvatarDescriptor avatar;
        readonly string[] names = { "AI_Smile", "AI_Sad", "AI_Angry", "AI_Surprised", "AI_BrowUp", "AI_Cheek" };
        readonly string[] shapes = {
            "mouthSmileLeft,mouthSmileRight,Fcl_ALL_Joy,Joy",
            "mouthFrownLeft,mouthFrownRight,Fcl_ALL_Sorrow,Sorrow",
            "browDownLeft,browDownRight,Fcl_ALL_Angry,Angry",
            "eyeWideLeft,eyeWideRight,Fcl_ALL_Surprised,Surprised",
            "browInnerUp", "cheekSquintLeft,cheekSquintRight"
        };

        [MenuItem("VIREA/Prepare VRChat Avatar Copy")]
        static void Open() => GetWindow<VireaAvatarSetup>("VIREA Avatar");

        void OnGUI()
        {
            EditorGUILayout.HelpBox("Creates a disabled avatar copy and new controller assets. Existing avatar and assets remain untouched. Import/convert the VRM with VRM Converter for VRChat first. Native microphone lip sync stays with VRChat.", MessageType.Info);
            avatar = (VRCAvatarDescriptor)EditorGUILayout.ObjectField("Converted avatar", avatar, typeof(VRCAvatarDescriptor), true);
            EditorGUILayout.LabelField("Blendshape names (comma-separated, exact matching)", EditorStyles.boldLabel);
            for (int i = 0; i < names.Length; i++) shapes[i] = EditorGUILayout.TextField(names[i], shapes[i]);
            EditorGUILayout.HelpBox("65 synced bits: six floats, two hand-pose integers, AI_Active bool. Verify face bindings and hand curves in Unity Preview before Build & Test. Missing face shapes are reported, never invented.", MessageType.None);
            using (new EditorGUI.DisabledScope(avatar == null))
                if (GUILayout.Button("Create VIREA avatar copy"))
                    try { Build(); } catch (Exception error) { Debug.LogException(error); EditorUtility.DisplayDialog("VIREA", error.Message, "OK"); }
        }

        public static GameObject CreateAvatarCopy(VRCAvatarDescriptor source)
        {
            var setup = CreateInstance<VireaAvatarSetup>();
            try { setup.avatar = source; return setup.Build(); }
            finally { DestroyImmediate(setup); }
        }

        GameObject Build()
        {
            if (EditorUtility.IsPersistent(avatar)) throw new InvalidOperationException("Select an avatar instance in the scene.");
            var existing = avatar.expressionParameters?.parameters ?? Array.Empty<VRCExpressionParameters.Parameter>();
            if (existing.Any(p => p.name.StartsWith("AI_"))) throw new InvalidOperationException("AI_ parameters already exist. Start from the original avatar to avoid duplicate layers.");
            int cost = existing.Where(p => p.networkSynced).Sum(p => p.valueType == VRCExpressionParameters.ValueType.Bool ? 1 : 8);
            if (cost + 65 > 256) throw new InvalidOperationException($"Expression parameter budget exceeded: {cost}+65 > 256.");
            var animator = avatar.GetComponent<Animator>();
            if (!animator || !animator.isHuman) throw new InvalidOperationException("A valid Humanoid Animator is required.");
            var fxSource = ControllerSource(avatar, VRCAvatarDescriptor.AnimLayerType.FX, "vrc_AvatarV3FaceLayer");
            var gestureSource = ControllerSource(avatar, VRCAvatarDescriptor.AnimLayerType.Gesture, "vrc_AvatarV3HandsLayer");
            if (!AssetDatabase.IsValidFolder("Assets/VIREA")) AssetDatabase.CreateFolder("Assets", "VIREA");
            string folder = "Assets/VIREA/Avatar-" + Guid.NewGuid().ToString("N").Substring(0, 8);
            AssetDatabase.CreateFolder("Assets/VIREA", folder.Split('/').Last());
            var copy = Instantiate(avatar.gameObject, avatar.transform.parent);
            copy.name = avatar.gameObject.name + "-VIREA";
            copy.SetActive(false);
            Undo.RegisterCreatedObjectUndo(copy, "Create VIREA avatar");
            var descriptor = copy.GetComponent<VRCAvatarDescriptor>();
            var parameters = CreateInstance<VRCExpressionParameters>();
            var list = new List<VRCExpressionParameters.Parameter>(existing);
            foreach (var name in names) list.Add(Parameter(name, VRCExpressionParameters.ValueType.Float));
            list.Add(Parameter("AI_LeftHandPose", VRCExpressionParameters.ValueType.Int));
            list.Add(Parameter("AI_RightHandPose", VRCExpressionParameters.ValueType.Int));
            list.Add(Parameter("AI_Active", VRCExpressionParameters.ValueType.Bool));
            parameters.parameters = list.ToArray();
            AssetDatabase.CreateAsset(parameters, folder + "/Parameters.asset");
            descriptor.expressionParameters = parameters;
            descriptor.customExpressions = true;
            descriptor.customizeAnimationLayers = true;
            var fx = CopyController(fxSource, folder + "/FX.controller");
            var gesture = CopyController(gestureSource, folder + "/Gesture.controller");
            var faceLayers = new List<int>();
            for (int i = 0; i < names.Length; i++)
            {
                var bindings = new List<EditorCurveBinding>();
                var allowed = shapes[i].Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).ToHashSet(StringComparer.OrdinalIgnoreCase);
                foreach (var mesh in copy.GetComponentsInChildren<SkinnedMeshRenderer>(true))
                    if (mesh.sharedMesh)
                        for (int j = 0; j < mesh.sharedMesh.blendShapeCount; j++)
                        {
                            string shape = mesh.sharedMesh.GetBlendShapeName(j);
                            if (allowed.Contains(shape)) bindings.Add(EditorCurveBinding.FloatCurve(AnimationUtility.CalculateTransformPath(mesh.transform, copy.transform), typeof(SkinnedMeshRenderer), "blendShape." + shape));
                        }
                if (bindings.Count == 0) { Debug.LogWarning("VIREA: no blendshape binding for " + names[i], copy); continue; }
                fx.AddParameter(names[i], AnimatorControllerParameterType.Float);
                var state = AddLayer(fx, names[i], out int index);
                faceLayers.Add(index);
                var low = Clip(folder, names[i] + "-0");
                var high = Clip(folder, names[i] + "-1");
                foreach (var binding in bindings)
                {
                    AnimationUtility.SetEditorCurve(low, binding, AnimationCurve.Constant(0, 1, 0));
                    AnimationUtility.SetEditorCurve(high, binding, AnimationCurve.Constant(0, 1, 100));
                }
                var tree = new BlendTree { name = names[i], blendType = BlendTreeType.Simple1D, blendParameter = names[i], useAutomaticThresholds = false };
                tree.AddChild(low, 0); tree.AddChild(high, 1);
                AssetDatabase.AddObjectToAsset(tree, fx); state.motion = tree;
            }
            var handLayers = new List<int>();
            foreach (string side in new[] { "Left", "Right" })
            {
                string parameter = "AI_" + side + "HandPose";
                gesture.AddParameter(parameter, AnimatorControllerParameterType.Int);
                AddLayer(gesture, parameter, out int index);
                handLayers.Add(index);
                var layer = gesture.layers[index];
                var mask = new AvatarMask();
                for (int body = 0; body < (int)AvatarMaskBodyPart.LastBodyPart; body++) mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)body, false);
                mask.SetHumanoidBodyPartActive(side == "Left" ? AvatarMaskBodyPart.LeftFingers : AvatarMaskBodyPart.RightFingers, true);
                AssetDatabase.CreateAsset(mask, folder + "/" + side + "Fingers.mask");
                layer.avatarMask = mask;
                var layers = gesture.layers; layers[index] = layer; gesture.layers = layers;
                for (int pose = 0; pose <= 4; pose++)
                {
                    var clip = Clip(folder, side + "Hand-" + pose);
                    foreach (string finger in new[] { "Thumb", "Index", "Middle", "Ring", "Little" })
                        for (int joint = 1; joint <= 3; joint++)
                        {
                            bool open = pose == 2 || (pose == 3 && finger == "Index") || (pose == 4 && (finger == "Index" || finger == "Middle"));
                            float stretch = pose == 0 ? 0 : open ? 1 : -0.8f;
                            string muscle = side + " " + finger + " " + joint + " Stretched";
                            if (!HumanTrait.MuscleName.Contains(muscle)) throw new InvalidOperationException("Unknown humanoid muscle: " + muscle);
                            string property = side + "Hand." + finger + "." + joint + " Stretched";
                            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), property), AnimationCurve.Constant(0, 1, stretch));
                        }
                    var state = layer.stateMachine.AddState("Pose " + pose); state.motion = clip; state.writeDefaultValues = false;
                    var transition = layer.stateMachine.AddAnyStateTransition(state); transition.hasExitTime = false; transition.duration = 0.12f; transition.canTransitionToSelf = false;
                    transition.AddCondition(AnimatorConditionMode.Equals, pose, parameter);
                    if (pose == 0) layer.stateMachine.defaultState = state;
                }
            }
            Gate(fx, "FX", faceLayers); Gate(gesture, "Gesture", handLayers);
            Assign(descriptor, VRCAvatarDescriptor.AnimLayerType.FX, fx);
            Assign(descriptor, VRCAvatarDescriptor.AnimLayerType.Gesture, gesture);
            EditorUtility.SetDirty(descriptor); EditorUtility.SetDirty(fx); EditorUtility.SetDirty(gesture);
            AssetDatabase.SaveAssets(); Selection.activeGameObject = copy;
            Debug.Log("VIREA avatar copy created at " + folder + ". Activate only this copy for Build & Test; inspect warnings and lip sync first.", copy);
            return copy;
        }

        static VRCExpressionParameters.Parameter Parameter(string name, VRCExpressionParameters.ValueType type) => new VRCExpressionParameters.Parameter { name = name, valueType = type, defaultValue = 0, saved = false, networkSynced = true };
        static AnimationClip Clip(string folder, string name) { var clip = new AnimationClip { name = name }; AssetDatabase.CreateAsset(clip, folder + "/" + name + ".anim"); return clip; }
        static AnimatorState AddLayer(AnimatorController controller, string name, out int index)
        {
            controller.AddLayer("VIREA " + name); var layers = controller.layers; index = layers.Length - 1; layers[index].defaultWeight = 0; controller.layers = layers;
            var state = layers[index].stateMachine.AddState("Default"); state.writeDefaultValues = false; layers[index].stateMachine.defaultState = state; return state;
        }
        static AnimatorController ControllerSource(VRCAvatarDescriptor avatar, VRCAvatarDescriptor.AnimLayerType type, string defaultName)
        {
            var layer = avatar.baseAnimationLayers.First(l => l.type == type);
            if (!layer.isDefault && layer.animatorController)
                return layer.animatorController as AnimatorController ?? throw new InvalidOperationException("AnimatorOverrideController is not supported; provide an editable AnimatorController.");
            var source = AssetDatabase.FindAssets(defaultName + " t:AnimatorController").Select(AssetDatabase.GUIDToAssetPath).FirstOrDefault(p => System.IO.Path.GetFileNameWithoutExtension(p) == defaultName);
            if (source == null) throw new InvalidOperationException("SDK default controller missing: " + defaultName + ". Import SDK avatar samples or assign a custom controller first.");
            return AssetDatabase.LoadAssetAtPath<AnimatorController>(source);
        }
        static AnimatorController CopyController(AnimatorController source, string target)
        {
            if (!AssetDatabase.CopyAsset(AssetDatabase.GetAssetPath(source), target)) throw new InvalidOperationException("Could not copy controller.");
            return AssetDatabase.LoadAssetAtPath<AnimatorController>(target);
        }
        static void Assign(VRCAvatarDescriptor avatar, VRCAvatarDescriptor.AnimLayerType type, AnimatorController controller)
        {
            var layers = avatar.baseAnimationLayers; int index = Array.FindIndex(layers, l => l.type == type); layers[index].isDefault = false; layers[index].animatorController = controller; avatar.baseAnimationLayers = layers;
        }
        static void Gate(AnimatorController controller, string playable, List<int> controlled)
        {
            controller.AddParameter("AI_Active", AnimatorControllerParameterType.Bool);
            AddLayer(controller, "Gate", out int index);
            var layers = controller.layers; layers[index].defaultWeight = 1; controller.layers = layers;
            var machine = layers[index].stateMachine;
            var inactive = machine.defaultState; inactive.name = "Release";
            var active = machine.AddState("Drive"); active.writeDefaultValues = false;
            foreach (var pair in new[] { (state: inactive, weight: 0f), (state: active, weight: 1f) })
                foreach (int target in controlled)
                {
                    var behaviour = pair.state.AddStateMachineBehaviour<VRCAnimatorLayerControl>();
                    var serialized = new SerializedObject(behaviour);
                    var playableProperty = serialized.FindProperty("playable");
                    int enumIndex = Array.IndexOf(playableProperty.enumNames, playable);
                    if (enumIndex < 0) throw new InvalidOperationException("Unsupported SDK playable layer " + playable);
                    playableProperty.enumValueIndex = enumIndex;
                    serialized.FindProperty("layer").intValue = target;
                    serialized.FindProperty("goalWeight").floatValue = pair.weight;
                    serialized.FindProperty("blendDuration").floatValue = 0.15f;
                    serialized.ApplyModifiedPropertiesWithoutUndo();
                }
            var enter = inactive.AddTransition(active); enter.hasExitTime = false; enter.duration = 0; enter.AddCondition(AnimatorConditionMode.If, 0, "AI_Active");
            var leave = active.AddTransition(inactive); leave.hasExitTime = false; leave.duration = 0; leave.AddCondition(AnimatorConditionMode.IfNot, 0, "AI_Active");
        }
    }
}
#endif
