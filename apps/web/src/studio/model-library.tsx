import {useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import {Button,Card,Chip,Input,Label,ListBox,Modal,ProgressBar,Select} from "@heroui/react";
import {AudioLines,Check,Download,Search} from "lucide-react";
import {api,request} from "../api";
import type {ModelManifest,ModelExecutionOptions,ExecutionTargetSelection} from "../contracts";
import {usePreferences} from "./chrome";
import {t} from "./preferences";
import {bytes} from "./setup-panels";
import {translateLabel} from "./legacy";

type Progress={model_id:string;status:string;stage?:string;message?:string;started_at?:number;updated_at?:number;transfer?:{artifact_id:string;completed_bytes:number;total_bytes?:number|null;bytes_per_second?:number|null;phase?:string;done?:boolean}|null;result?:{diagnostics?:string[]}};
function transferLabel(phase?:string) {
  switch(phase) {
    case "verify-local": case "integrity": return t("本地校验", "Local verification");
    case "reuse": return t("本地复用", "Local reuse");
    case "download": return t("网络下载", "Network download");
    case "reconstruction": return t("本地重建", "Local reconstruction");
    default: return t("模型文件处理", "Processing model files");
  }
}
function Choice({label,value,rows,onChange}:{label:string;value:string;rows:{id:string;name:string;disabled?:boolean}[];onChange:(id:string)=>void}) {
  return <Select fullWidth placeholder={t("请选择", "Select an option")} value={value || null} onChange={key=>onChange(String(key))} disabledKeys={rows.filter(r=>r.disabled).map(r=>r.id)}><Label>{label}</Label><Select.Trigger><Select.Value/><Select.Indicator/></Select.Trigger><Select.Popover className="mw-select-popover"><ListBox>{rows.map(r=><ListBox.Item id={r.id} key={r.id} textValue={r.name}><Label>{r.name}</Label><ListBox.ItemIndicator/></ListBox.Item>)}</ListBox></Select.Popover></Select>;
}
function ModelLibrary() {
  usePreferences();
  const [models,setModels]=useState<ModelManifest[]>([]),[search,setSearch]=useState("");
  const [chosen,setChosen]=useState<ModelManifest|null>(null),[options,setOptions]=useState<ModelExecutionOptions|null>(null);
  const [domain,setDomain]=useState(""),[variant,setVariant]=useState(""),[accepted,setAccepted]=useState(false);
  const [progress,setProgress]=useState<Progress[]>([]),[error,setError]=useState(""),[submitting,setSubmitting]=useState(false),[loading,setLoading]=useState(true);
  const [local,setLocal]=useState<{model_id:string;artifacts:string[];total_artifacts:number}[]>([]);
  const [loadError,setLoadError]=useState("");
  const refresh=async()=>{try {const [catalog,rows]=await Promise.all([api.models(),request<Progress[]>("/onboarding/model-deployments",{headers:{"X-Virea-Setup":"1"}})]);setModels(catalog);setProgress(rows);setLoadError("");}catch(e){setLoadError(String(e));}finally{setLoading(false);}};
  useEffect(()=>{void request<{models:typeof local}>("/onboarding/model-library",{headers:{"X-Virea-Setup":"1"}}).then(data=>setLocal(data.models)).catch(()=>{});},[]);
  useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>clearInterval(timer);},[]);
  const choose=async(model:ModelManifest)=>{setChosen(model);setOptions(null);setAccepted(false);setVariant("");setError("");try {const data=await api.executionOptions(model.model.id);setOptions(data);const best=data.options.find(o=>o.implemented&&o.can_build);setDomain(best?.execution_domain.id ?? data.options[0]?.execution_domain.id ?? "");}catch(e){setError(String(e));}};
  useEffect(()=>{const id=new URLSearchParams(location.search).get("model");const model=models.find(m=>m.model.id===id);if(model&&!chosen){void choose(model);history.replaceState(null,"",`${location.pathname}#motion-models`);}},[models]);
  const option=options?.options.find(o=>o.execution_domain.id===domain);
  const install=async()=>{
    if(!chosen||!domain)return;const model=chosen;setSubmitting(true);setError("");
    const target:ExecutionTargetSelection={schema_version:"virea.execution_target_selection.v1.0.0",execution_domain_id:domain,runtime_variant_id:variant||option?.selected_runtime_id||null,resource_profile_id:null};
    setProgress(rows=>[{model_id:model.model.id,status:"running",stage:"detect",message:t("提交部署请求", "Submitting deployment"),started_at:Date.now()/1000},...rows.filter(p=>p.model_id!==model.model.id)]);setChosen(null);
    try {const payload=await import("../domain");const result=await request<{state:string}>("/models/install",{method:"POST",body:JSON.stringify({...payload.createInstallPayload(model,target),accepted_license:accepted})},{timeoutMs:4*60*60*1000});if(result.state!=="READY")setError(t("部署尚未完成，请展开模型卡片查看诊断。", "Deployment is incomplete. Expand its card for diagnostics."));}
    catch(e){setError(String(e));}finally{setSubmitting(false);void refresh();}
  };
  const visible=models.filter(m=>`${m.model.display_name} ${m.model.id} ${m.output.skeleton_id}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="section-heading"><div><AudioLines size={21}/><h2>{t("动作模型库", "Motion model library")}</h2><Chip size="sm">{models.length}</Chip></div>
    <p className="hint">{t("模型安装、计算设备与生成验收统一在这里。完成后即可进入动作实验室创作。", "Install models, choose compute and verify generation here. Then create in Motion Lab.")}</p></div>
    <div className="mw-library-search"><Search size={16}/><Input aria-label={t("搜索动作模型", "Search motion models")} placeholder={t("按名称或骨骼格式搜索", "Search by name or skeleton")} value={search} onChange={e=>setSearch(e.target.value)}/><Button variant="ghost" onPress={()=>void refresh()}>{t("刷新", "Refresh")}</Button></div>
    {(error||loadError)&&<p className="inline-error" role="alert">{error||loadError}</p>}{loading&&<p className="hint">{t("正在读取已有模型…", "Reading installed models…")}</p>}
    <div className="mw-model-library">{visible.map(m=>{const p=progress.find(r=>r.model_id===m.model.id);const ready=m.installation?.ready;const active=p?.status==="running"&&!ready;const found=local.find(r=>r.model_id===m.model.id);return <Card key={m.model.id} className="mw-model-card" data-model-id={m.model.id}>
      <Card.Header><span className="mw-model-symbol"><AudioLines size={19}/></span><div><Card.Title>{m.model.display_name}</Card.Title><Chip size="sm" className={ready?"mw-status-succeeded":""}>{active?t("部署中", "Deploying"):ready?t("已就绪", "Ready"):found?t("本地已有", "Found locally"):t("可部署", "Available")}</Chip></div></Card.Header>
      <Card.Content><div className="mw-model-facts"><Chip size="sm">{m.output.skeleton_id}</Chip><Chip size="sm">{m.output.representation_id}</Chip>{Array.from(new Set(m.runtime_variants.map(r=>r.accelerator.kind === "cpu" ? "CPU" : "GPU"))).map(v=><Chip size="sm" key={v}>{v}</Chip>)}</div>
      {found&&!ready&&<p className="hint">{t("已找到本地文件", "Local files found")} · {found.artifacts.length}/{found.total_artifacts} · {t("部署时复用", "Reused on deployment")}</p>}
      {p&&!(ready&&p.status==="running")&&<div className="mw-model-progress"><p>{active&&p.transfer?transferLabel(p.transfer.phase):translateLabel(p.message??p.status)}</p>{active&&<><ProgressBar aria-label={p.transfer?`${transferLabel(p.transfer.phase)}${t("进度", " progress")}`:t("部署进度", "Deployment progress")} isIndeterminate={!p.transfer?.total_bytes} value={p.transfer?.total_bytes?100*p.transfer.completed_bytes/p.transfer.total_bytes:undefined}><ProgressBar.Track><ProgressBar.Fill/></ProgressBar.Track></ProgressBar><small>{p.transfer?`${p.transfer.artifact_id} · ${bytes(p.transfer.completed_bytes)} / ${bytes(p.transfer.total_bytes)}${p.transfer.bytes_per_second?` · ${bytes(p.transfer.bytes_per_second)}/s`:""}`:t("准备环境或执行真实生成检验", "Preparing the environment or running real inference")}</small></>}{p.result?.diagnostics?.length?<details><summary>{t("部署详情", "Deployment details")}</summary><pre>{p.result.diagnostics.join("\n")}</pre></details>:null}</div>}
      </Card.Content><Card.Footer>{ready?<a className="button button--secondary" href={`./?model=${encodeURIComponent(m.model.id)}`}>{t("在动作实验室使用", "Open in Motion Lab")} <Check size={14}/></a>:<Button variant="secondary" isDisabled={active||submitting||!m.capability?.installable} onPress={()=>void choose(m)}><Download size={14}/>{found?t("接入已有模型", "Connect existing model"):t("部署与检验", "Deploy & verify")}</Button>}{ready&&<Button variant="ghost" isDisabled={active||submitting} onPress={()=>void choose(m)}>{t("管理", "Manage")}</Button>}</Card.Footer>
    </Card>;})}</div>
    <Modal><Modal.Backdrop isOpen={!!chosen} onOpenChange={open=>{if(!open)setChosen(null);}}><Modal.Container size="md"><Modal.Dialog className="mw-model-dialog"><Modal.CloseTrigger aria-label={t("关闭", "Close")}/><Modal.Header><Modal.Heading>{chosen?.model.display_name}</Modal.Heading></Modal.Header><Modal.Body>
      {!options?<p>{t("检测兼容的运行环境…", "Checking compatible runtimes…")}</p>:<><Choice label={t("运行环境", "Environment")} value={domain} rows={options.options.map(o=>({id:o.execution_domain.id,name:`${o.execution_domain.platform} · ${o.execution_domain.distribution||o.execution_domain.kind}`,disabled:!o.implemented}))} onChange={id=>{setDomain(id);setVariant("");}}/>
      <Choice label={t("计算设备", "Compute device")} value={variant||"auto"} rows={[{id:"auto",name:t("自动选择（推荐）", "Automatic (recommended)")},...(chosen?.runtime_variants??[]).map(r=>({id:r.id,name:`${r.accelerator.kind==="cpu"?"CPU":r.accelerator.kind==="mps"?"Apple GPU":"NVIDIA GPU"} · ${r.accelerator.abi||r.python}`}))]} onChange={id=>setVariant(id==="auto"?"":id)}/>
      {option?.reasons?.length?<p className="hint">{option.reasons.join(" · ")}</p>:null}
      <label className="mw-license"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/><span>{t("我已阅读模型许可，同意下载与安装。部署后会运行真实生成验收。", "I have reviewed the model license and agree to install it. Deployment includes a real generation check.")}</span></label><a href={`https://github.com/Moonweave-AI/virea/tree/main/plugins/models/${chosen?.model.id}`} target="_blank" rel="noreferrer">{t("模型来源与许可 ↗", "Sources & license ↗")}</a></>}{error&&<p role="alert">{error}</p>}
      </Modal.Body><Modal.Footer><Button variant="secondary" onPress={()=>setChosen(null)}>{t("取消", "Cancel")}</Button><Button isDisabled={!accepted||!option?.implemented||(!option.can_build&&!variant)||submitting} onPress={()=>void install()}>{t("开始部署", "Start deployment")}</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
  </>;
}
export function mountModelLibrary(host:HTMLElement){host.dataset.uiOwned="true";createRoot(host).render(<ModelLibrary/>);}
