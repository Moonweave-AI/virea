import {useEffect, useState} from "react";
import {createRoot, type Root} from "react-dom/client";
import {Button, Card, Chip, ProgressBar} from "@heroui/react";
import {Activity, Cpu, HardDrive, MemoryStick, Monitor, Terminal, Download, Check, Clock, CircleAlert, ArrowUpRight} from "lucide-react";
import {t} from "./preferences";
import {usePreferences} from "./chrome";
import {translateLabel} from "./legacy";
import {InstallerMeter, type InstallerProgress} from "./installer-progress";

export interface HardwareReport {
  platform: string; architecture: string; data_directory: string; memory_gib?:number; free_disk_gib:number;
  services:unknown[];
  hardware?: {
    measured_at:string; system:{name:string;release:string;architecture:string;python:string};
    cpu:{name:string;physical_cores:number|null;logical_cores:number;utilization_percent:number};
    memory:{total_bytes:number;available_bytes:number;used_bytes:number;swap_total_bytes:number};
    storage:{path:string;total_bytes:number;available_bytes:number;used_bytes:number};
    disks:{mount:string;filesystem:string;total_bytes:number;available_bytes:number}[];
    gpus:{name:string;vendor?:string;total_bytes:number|null;available_bytes:number|null;memory_kind:string;driver?:string;source:string}[];
    tools:Record<string,{available:boolean;path:string|null}>;
  };
}
export interface DeploymentJob {
  id:string;status:string;message:string;step:number;total_steps:number;percent:number;stage_percent:number|null;
  downloaded_bytes?:number;total_bytes?:number;bytes_per_second?:number;elapsed_seconds?:number;eta_seconds?:number|null;
  output_age_seconds?:number|null;file?:string|null;files_done?:number|null;files_total?:number|null;logs?:{time:number;message:string}[];
  process?:InstallerProgress|null;request:Record<string,unknown>;result?:{verification?:unknown};
}
const roots = new WeakMap<HTMLElement,Root>();
function render(host:HTMLElement, content:React.ReactNode) {host.dataset.uiOwned="true";let root=roots.get(host);if(!root){root=createRoot(host);roots.set(host,root);}root.render(content);}
export function bytes(value:number|null|undefined):string {
  if(value == null) return t("未提供", "Not reported");
  if(value >= 1073741824) return `${(value/1073741824).toFixed(1)} GiB`;
  if(value >= 1048576) return `${(value/1048576).toFixed(1)} MiB`;
  return `${(value/1024).toFixed(0)} KiB`;
}
const duration = (seconds:number) => seconds>=60 ? `${Math.floor(seconds/60)}m ${Math.round(seconds%60)}s` : `${Math.round(seconds)}s`;
function Bar({value,label}:{value:number|null;label:string}) {
  return <ProgressBar aria-label={label} value={value ?? undefined} isIndeterminate={value==null} className="mw-progress"><ProgressBar.Track><ProgressBar.Fill/></ProgressBar.Track></ProgressBar>;
}
function DeviceReport({report}:{report:HardwareReport}) {
  usePreferences();
  const h=report.hardware;
  const cells = [
    {Icon:Monitor,name:t("系统", "Operating system"),value:h ? `${h.system.name} ${h.system.release}` : report.platform, detail:`${report.architecture} · Python ${h?.system.python ?? "—"}`},
    {Icon:Cpu,name:t("处理器", "Processor"),value:h?.cpu.name || "—",detail:h ? `${h.cpu.physical_cores ?? "—"} ${t("核", "cores")} / ${h.cpu.logical_cores} ${t("线程", "threads")} · ${h.cpu.utilization_percent}% ${t("使用中", "in use")}` : "—"},
    {Icon:MemoryStick,name:t("可用内存", "Available memory"),value:bytes(h?.memory.available_bytes),detail:`${t("总计", "Total")} ${bytes(h?.memory.total_bytes ?? (report.memory_gib ? report.memory_gib*1073741824 : null))}`,percent:h ? (1-h.memory.available_bytes/h.memory.total_bytes)*100 : undefined},
    {Icon:HardDrive,name:t("可用磁盘", "Available storage"),value:bytes(h?.storage.available_bytes ?? report.free_disk_gib*1073741824),detail:`${t("总计", "Total")} ${bytes(h?.storage.total_bytes)}`,percent:h ? (1-h.storage.available_bytes/h.storage.total_bytes)*100 : undefined},
  ];
  return <div className="mw-device-report"><div className="mw-device-grid">{cells.map(({Icon,name,value,detail,percent}) => <Card key={name} className="mw-metric"><Card.Header><Icon size={18}/><span>{name}</span></Card.Header><Card.Content><strong title={value}>{value}</strong><small>{detail}</small>{percent!==undefined && <Bar value={percent} label={`${name} ${t("使用率", "usage")}`}/>}</Card.Content></Card>)}</div>
    <div className="mw-device-detail"><div className="mw-detail-heading"><Cpu size={17}/><h3>{t("图形与加速", "Graphics & acceleration")}</h3><Chip size="sm">{report.services.length} {t("个本地服务", "local services")}</Chip></div>
      {h?.gpus.length ? h.gpus.map((gpu,i) => <div className="mw-gpu" key={i}><div><strong>{gpu.name}</strong><small>{gpu.driver ? `${t("驱动", "Driver")} ${gpu.driver}` : gpu.source}</small></div><div><strong>{bytes(gpu.available_bytes)} <span>{t("可用", "available")}</span></strong><small>{gpu.memory_kind === "unified" ? t("与系统内存共享", "Unified system memory") : `${t("显存总计", "Total VRAM")} ${bytes(gpu.total_bytes)}`}</small></div></div>) : <p>{t("未发现可读取的 GPU 信息，CPU 模型仍可部署。", "GPU telemetry is unavailable. CPU models can still be deployed.")}</p>}
    </div>
    <details className="mw-hardware-details"><summary>{t("磁盘、工具与存储位置", "Disks, tools & storage location")}</summary><code>{report.data_directory}</code>
      {h && <><div className="mw-disk-list">{h.disks.map(d => <div key={d.mount}><span>{d.mount} <small>{d.filesystem}</small></span><span>{bytes(d.available_bytes)} / {bytes(d.total_bytes)} {t("可用", "free")}</span></div>)}</div><div className="mw-tools">{Object.entries(h.tools).map(([name,tool]) => <Chip key={name} size="sm" title={tool.path ?? undefined}>{tool.available ? <Check size={12}/> : <span>·</span>} {name}</Chip>)}</div><p className="hint">{t("检测时间", "Measured at")}: {new Date(h.measured_at).toLocaleTimeString()} · {t("未报告的显存不会计为零。", "Unavailable VRAM readings remain unknown.")}</p></>}
    </details>
  </div>;
}
const recipeNames: Record<string,string> = {motioncraft:"MotionCraft",syntalker:"SynTalker",audio8:"Audio8",kokoro:"Kokoro",ollama:"Ollama"};
const status = (key:string) => ({running:t("进行中","Running"),queued:t("排队中","Queued"),succeeded:t("已就绪","Ready"),failed:t("失败","Failed"),interrupted:t("已中断","Interrupted"),cancelled:t("已取消","Cancelled")}[key] ?? key);
type Service = {recipe:string;owned_running:boolean;auto_start:boolean};
function JobPanel({jobs,proofMarkup,services}:{jobs:DeploymentJob[];proofMarkup:(proof:any)=>string;services:Service[]}) {
  usePreferences();
  const steps = [t("检测", "Detect"),t("环境", "Environment"),t("依赖", "Dependencies"),t("权重", "Weights"),t("生成检验", "Generate"),t("就绪", "Ready")];
  const groups = new Map<string,DeploymentJob[]>();
  for (const job of jobs.slice().reverse()) {
    const key=String(job.request.recipe)+(job.request.recipe === "ollama" ? `:${job.request.model}` : "");
    groups.set(key,[...(groups.get(key) ?? []),job]);
  }
  return <div className="mw-jobs">{Array.from(groups,([key,attempts]) => {const job=attempts.find(j=>["running","queued"].includes(j.status)) ?? attempts[0]!;const active=["running","queued"].includes(job.status);return <Card className="mw-job" data-active={active} key={key}>
    <Card.Header><div className="mw-job-name"><span className="mw-job-symbol">{job.status === "succeeded" ? <Check size={20}/> : job.status === "failed" ? <CircleAlert size={20}/> : <Download size={20}/>}</span><div><strong>{recipeNames[String(job.request.recipe)] ?? String(job.request.recipe)}</strong><Chip size="sm" className={`mw-status-${job.status}`}>{status(job.status)}</Chip></div></div><span className="mw-job-percent">{job.percent}% · [{job.step}/{job.total_steps}]</span></Card.Header>
    <Card.Content>{active && <><Bar value={job.percent} label={t("整体部署进度", "Overall deployment progress")}/><ol className="mw-stepper">{steps.map((step,i) => <li key={step} data-state={job.step>i+1 ? "done" : job.step===i+1 ? "active" : "pending"}><span>{job.step>i+1 ? <Check size={11}/> : i+1}</span>{step}</li>)}</ol></>}
    <p className="mw-current-step" role="status">{translateLabel(job.message)}</p>
    {job.status === "running" && job.process && <InstallerMeter value={job.process}/>}
    {job.status === "running" && !job.process && <><Bar value={job.stage_percent} label={t("当前步骤进度", "Current step progress")}/><div className="mw-transfer"><span>{job.file || (job.stage_percent == null ? t("正在处理 · 总量尚未报告", "Working · total not yet reported") : `${t("当前步骤", "Current step")} ${job.stage_percent}%`)}</span><span>{job.total_bytes ? `${bytes(job.downloaded_bytes)} / ${bytes(job.total_bytes)}` : ""}</span></div><div className="mw-job-facts"><span><Clock size={13}/>{duration(job.elapsed_seconds ?? 0)}</span>{!!job.bytes_per_second && <span>{bytes(job.bytes_per_second)}/s</span>}{job.eta_seconds!=null && <span>{t("剩余约", "About")} {duration(job.eta_seconds)}</span>}{job.files_total!=null && <span>{job.files_done ?? 0}/{job.files_total} {t("文件", "files")}</span>}</div>{job.output_age_seconds!=null && job.output_age_seconds>20 && <p className="hint">{t(`最近一条输出在 ${Math.round(job.output_age_seconds)} 秒前；仍在等待此步骤完成。`, `Last output ${Math.round(job.output_age_seconds)}s ago; waiting for this step to finish.`)}</p>}</>}
    {job.logs?.length ? <details className="mw-job-log"><summary><Terminal size={14}/>{t("过程日志", "Process log")} · {job.logs.length}</summary><pre>{job.logs.map(line=>`${new Date(line.time*1000).toLocaleTimeString()}  ${line.message}`).join("\n")}</pre></details> : null}
    {job.status === "succeeded" && <div dangerouslySetInnerHTML={{__html:proofMarkup(job.result?.verification).replace(/(<details[^>]*?)\sopen/g, "$1")}}/>}
    {attempts.length>1 && <details className="mw-attempts"><summary>{t("部署历史", "Deployment history")} · {attempts.length}</summary>{attempts.filter(a=>a.id!==job.id).map(a=><div key={a.id}><Chip size="sm" className={`mw-status-${a.status}`}>{status(a.status)}</Chip><span>{String(a.request.device ?? "auto").toUpperCase()}</span><small>{translateLabel(a.message)}</small></div>)}</details>}
    {services.some(s=>s.recipe===job.request.recipe&&s.auto_start)&&<details className="mw-service-settings"><summary>{t("服务设置", "Service settings")}</summary><p className="hint">{t("下次启动 VIREA 时自动恢复此服务。", "This service starts automatically with VIREA.")}</p><Button variant="ghost" size="sm" data-stop={String(job.request.recipe)}>{t("停止并关闭自动启动", "Stop & disable auto-start")}</Button></details>}
    </Card.Content><Card.Footer>{active ? <Button variant="secondary" data-cancel={job.id}>{t("取消部署", "Cancel deployment")}</Button> : <Button variant="secondary" data-retry={job.id}>{job.status === "succeeded" ? t("重新生成检验", "Run generation test") : t("重试（复用缓存）", "Retry using cache")}</Button>}{active && <small>{t("关闭页面后，任务仍会继续", "Deployment continues if you close this page")}</small>}</Card.Footer>
  </Card>;})}</div>;
}
function ActivityPanel() {
  usePreferences();
  const [rows,setRows] = useState<{sequence:number;time:number;category:string;message:string;status:string}[]>([]);
  const [connected,setConnected] = useState(false);
  useEffect(() => {
    let alive=true,cursor=0;let timer:ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response=await fetch(`/api/v1/onboarding/activity?after=${cursor}`,{headers:{"X-Virea-Setup":"1"},signal:AbortSignal.timeout(5000)});
        if(!response.ok) throw new Error("unavailable");
        const data=await response.json();if(!alive)return;
        if(!Array.isArray(data.events)) throw new Error("invalid activity response");
        cursor=data.cursor;setConnected(true);
        setRows(previous => [...(data.reset ? [] : previous),...data.events].slice(-60));
      } catch {if(alive)setConnected(false);}
      finally {if(alive)timer=setTimeout(()=>void poll(),document.hidden?5000:1000);}
    };void poll();return()=>{alive=false;clearTimeout(timer);};
  },[]);
  return <Card className="mw-activity"><Card.Header><div><Activity size={17}/><strong>{t("实时活动", "Live activity")}</strong></div><Chip size="sm">{connected?t("实时同步", "Live"):t("重连中", "Reconnecting")}</Chip></Card.Header><Card.Content><p className="hint">{t("这里与启动终端显示同一份检测、部署和检验记录。", "Discovery, deployment and test events are shared with the launcher terminal.")}</p><div className="mw-activity-feed" role="log" aria-live="polite" aria-relevant="additions">{rows.length ? rows.slice().reverse().map(row=><div key={row.sequence}><time>{new Date(row.time*1000).toLocaleTimeString()}</time><span className={`mw-event-${row.status}`}>{row.status === "succeeded" ? <Check size={13}/> : row.status === "failed" ? <CircleAlert size={13}/> : <span>·</span>}</span><p><b>{recipeNames[row.category] ?? translateLabel(row.category)}</b>{translateLabel(row.message)}</p></div>) : <p className="hint">{t("开始检测或部署，进度会出现在这里。", "Start a scan or deployment to follow it here.")}</p>}</div></Card.Content></Card>;
}
export function showHardware(host:HTMLElement,report:HardwareReport) {render(host,<DeviceReport report={report}/>);}
export function showJobs(host:HTMLElement,jobs:DeploymentJob[],proofMarkup:(proof:any)=>string,services:Service[]=[]) {render(host,<JobPanel jobs={jobs} proofMarkup={proofMarkup} services={services}/>);}
export function mountActivity(host:HTMLElement) {render(host,<ActivityPanel/>);}
export function VerificationProgress({label}:{label:string}) {
  usePreferences();const[elapsed,setElapsed]=useState(0);
  useEffect(()=>{const start=Date.now();const timer=setInterval(()=>setElapsed((Date.now()-start)/1000),1000);return()=>clearInterval(timer);},[label]);
  return <div className="mw-verification-progress"><Bar value={null} label={t("真实生成检验", "Generation verification")}/><span>{label} · {duration(elapsed)}</span><small>{t("等待模型返回实际结果；语音保持静音。", "Waiting for actual model output. Speech stays silent.")}</small></div>;
}
export function showVerification(host:HTMLElement,label:string) {render(host,<VerificationProgress label={label}/>);}
export function clearPanel(host:HTMLElement) {roots.get(host)?.unmount();roots.delete(host);host.removeAttribute("data-ui-owned");}
