// Requires the official VRChat Avatars SDK and VRM Converter for VRChat.
#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using Esperecyan.Unity.VRMConverterForVRChat;

namespace Virea.VRChat.Editor
{
    public static class VireaProjectSetup
    {
        public const string ScenePath = "Assets/VIREA/Scenes/IndependentAI.unity";

        // Batch entry point; omit -quit so UniVRM's delayed texture import can finish.
        public static void Prepare()
        {
            var vrmPath = Environment.GetEnvironmentVariable("VIREA_VRM_ASSET") ?? "Assets/VIREASetup/VireaSource.vrm";
            var prefabPath = Path.ChangeExtension(vrmPath, ".prefab");
            if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath))
            {
                Complete(prefabPath);
                return;
            }
            VRM.vrmAssetPostprocessor.ImportVrmAndCreatePrefab(Path.GetFullPath(vrmPath), UniGLTF.UnityPath.FromUnityPath(prefabPath));
            var deadline = EditorApplication.timeSinceStartup + 120;
            void AwaitImport()
            {
                if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath))
                {
                    EditorApplication.update -= AwaitImport;
                    Complete(prefabPath);
                }
                else if (EditorApplication.timeSinceStartup > deadline)
                {
                    EditorApplication.update -= AwaitImport;
                    Debug.LogError("VRM prefab import timed out: " + prefabPath);
                    if (Application.isBatchMode) EditorApplication.Exit(1);
                }
            }
            EditorApplication.update += AwaitImport;
        }

        static void Complete(string prefabPath)
        {
            try
            {
                PrepareScene(prefabPath);
                if (Application.isBatchMode) EditorApplication.Exit(0);
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                if (Application.isBatchMode) EditorApplication.Exit(1);
                else throw;
            }
        }

        static void PrepareScene(string sourcePath)
        {
            if (File.Exists(ScenePath))
                throw new InvalidOperationException("Prepared scene already exists. Open it, or preserve it before regenerating.");
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(sourcePath);
            if (!source) throw new InvalidOperationException("VRM has not imported successfully: " + sourcePath);
            Folder("Assets/VIREA"); Folder("Assets/VIREA/VRChat"); Folder("Assets/VIREA/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            var converted = Duplicator.Duplicate(source, "Assets/VIREA/VRChat/Converted.prefab", Array.Empty<string>(), true);
            foreach (var message in Converter.Convert(converted, VRMUtility.GetAllVRMBlendShapeClips(source), false,
                Converter.SwayingObjectsConverterSetting.ConvertVrmSpringBonesAndVrmSpringBoneColliderGroups))
            {
                if (message.type == MessageType.Error) throw new InvalidOperationException(message.message);
                if (message.type == MessageType.Warning) Debug.LogWarning(message.message);
                else Debug.Log(message.message);
            }
            PrefabUtility.ApplyPrefabInstance(converted, InteractionMode.AutomatedAction);
            var prepared = VireaAvatarSetup.CreateAvatarCopy(converted.GetComponent<VRCAvatarDescriptor>());
            converted.SetActive(false);
            prepared.name = "VIREA Independent AI";
            prepared.SetActive(true);
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            AssetDatabase.SaveAssets();
            Validate();
        }

        // Verifies the prepared assets without uploading or logging into an account.
        public static void Validate()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath);
            var avatars = scene.GetRootGameObjects().SelectMany(root => root.GetComponentsInChildren<VRCAvatarDescriptor>())
                .Where(avatar => avatar.gameObject.activeInHierarchy).ToArray();
            if (avatars.Length != 1) throw new InvalidOperationException("Expected exactly one active AI avatar.");
            var avatar = avatars[0];
            if (!avatar.GetComponent<Animator>().isHuman) throw new InvalidOperationException("Avatar is not Humanoid.");
            var expected = new[] { "AI_Smile", "AI_Sad", "AI_Angry", "AI_Surprised", "AI_BrowUp", "AI_Cheek", "AI_LeftHandPose", "AI_RightHandPose", "AI_Active" };
            if (expected.Any(name => !avatar.expressionParameters.parameters.Any(parameter => parameter.name == name)))
                throw new InvalidOperationException("An AI expression parameter is missing.");
            if (avatar.expressionParameters.CalcTotalCost() > 256) throw new InvalidOperationException("Expression parameter budget exceeded.");
            foreach (var type in new[] { VRCAvatarDescriptor.AnimLayerType.FX, VRCAvatarDescriptor.AnimLayerType.Gesture })
                if (!avatar.baseAnimationLayers.Any(layer => layer.type == type && !layer.isDefault && layer.animatorController))
                    throw new InvalidOperationException("Missing custom controller: " + type);
            if (!avatar.VisemeSkinnedMesh || avatar.VisemeBlendShapes == null || avatar.VisemeBlendShapes.Length != 15)
                throw new InvalidOperationException("Native viseme blendshapes are not configured.");
            Debug.Log("VIREA_AVATAR_VALIDATED: Humanoid; 9 AI parameters; FX/Gesture controllers; 15 native visemes. Scene: " + ScenePath);
        }

        static void Folder(string path)
        {
            if (!AssetDatabase.IsValidFolder(path))
                AssetDatabase.CreateFolder(Path.GetDirectoryName(path).Replace('\\', '/'), Path.GetFileName(path));
        }
    }
}
#endif
