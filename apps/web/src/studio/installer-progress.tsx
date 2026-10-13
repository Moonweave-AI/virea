import {ProgressBar} from "@heroui/react";
import {t} from "./preferences";

export type InstallerProgress = {
  phase:string; file?:string; percent?:number|null; completed?:number; total?:number;
  completed_bytes?:number; total_bytes?:number; bytes_per_second?:number; eta_seconds?:number|null;
  updated_at?:number; message?:string;
};
const size=(n:number)=>n>=1073741824?`${(n/1073741824).toFixed(2)} GiB`:`${(n/1048576).toFixed(1)} MiB`;
export function InstallerMeter({value}:{value:InstallerProgress}) {
  const label=({resolve:t("解析依赖","Resolving dependencies"),download:t("下载依赖","Downloading dependencies"),prepare:t("准备安装包","Preparing packages"),install:t("安装依赖","Installing packages"),build:t("构建依赖","Building packages"),extract:t("解压安装包","Extracting packages"),reuse:t("检查已有依赖","Checking installed packages")} as Record<string,string>)[value.phase]??value.phase;
  const fresh=!value.updated_at||Date.now()/1000-value.updated_at<10;
  return <div className="mw-installer-meter" role="status">
    <div className="mw-transfer"><strong>{label}</strong><span>{value.percent!=null?`${Math.min(100,value.percent).toFixed(1)}%`:t("处理中","In progress")}</span></div>
    <ProgressBar aria-label={label} value={value.percent??undefined} isIndeterminate={value.percent==null}><ProgressBar.Track><ProgressBar.Fill/></ProgressBar.Track></ProgressBar>
    <div className="mw-transfer"><span>{value.file||""}</span><span>{value.total_bytes?`${size(value.completed_bytes??0)} / ${size(value.total_bytes)}`:value.total?`${value.completed??0}/${value.total} ${t("个依赖包","packages")}`:""}</span></div>
    <div className="mw-job-facts">{fresh&&!!value.bytes_per_second&&<span>{size(value.bytes_per_second)}/s</span>}{fresh&&value.eta_seconds!=null&&<span>{t("剩余约","About")} {value.eta_seconds}s</span>}{!fresh&&<span>{t("等待安装器下一条输出","Waiting for the installer's next update")}</span>}</div>
  </div>;
}
