// Remotion CLI（Studio / 渲染导出）打包配置：与 vite.config.ts 的 @proj/@demos 策略保持一致。
// 未链接成片工程时自动落到 proj-stub 降级实现；symlinks:false 让符号链接按
// 虚拟路径解析，裸导入落回本工程 node_modules（避免 react/remotion 双实例）。
import { existsSync } from "node:fs";
import path from "node:path";
import { Config } from "@remotion/cli/config";

const proj = path.resolve(
  process.cwd(),
  existsSync(path.resolve(process.cwd(), "proj", "workbench.ts")) ? "proj" : "proj-stub",
);

Config.overrideWebpackConfig((c) => ({
  ...c,
  resolve: {
    ...c.resolve,
    symlinks: false,
    alias: {
      ...(c.resolve?.alias ?? {}),
      "@proj": proj,
      "@demos": path.resolve(process.cwd(), "demosrc"),
    },
  },
}));

// Lossless source frames and an explicit SDR delivery color space.
Config.setVideoImageFormat("png");
Config.setPixelFormat("yuv420p");
Config.setColorSpace("bt709");
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer("angle");
Config.setConcurrency(4);
