import {createRoot, type Root} from "react-dom/client";
import {Select, ListBox, Label} from "@heroui/react";
import {subscribe, t} from "./preferences";
import {translateLabel} from "./legacy";

// Native elements remain the form and application contract. HeroUI owns the
// visible control, keyboard navigation, focus return and animated popover.
export function enhanceSelects(container:HTMLElement) {
  const controls = new Map<HTMLSelectElement,{host:HTMLElement;root:Root;signature:string;restore:()=>void}>();
  let queued = false;
  let resetting = false;
  // Value setters do not emit DOM mutations or change events. Bridge these
  // instance properties without changing application events or global prototypes.
  function watchValue(native:HTMLSelectElement) {
    const restore:(()=>void)[]=[];
    for(const key of ["value","selectedIndex"] as const) {
      const own=Object.getOwnPropertyDescriptor(native,key);
      const descriptor=own ?? Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,key)!;
      if(!descriptor.get || !descriptor.set || descriptor.configurable===false)continue;
      Object.defineProperty(native,key,{
        configurable:true,enumerable:descriptor.enumerable,
        get(){return descriptor.get!.call(this);},
        set(value){descriptor.set!.call(this,value);schedule();},
      });
      restore.push(()=>{if(own)Object.defineProperty(native,key,own);else Reflect.deleteProperty(native,key);});
    }
    return ()=>restore.forEach(reset=>reset());
  }
  function sync() {
    queued = false;
    for (const [native, entry] of controls) {
      if (!container.contains(native)) {entry.restore();native.removeEventListener("change",schedule);entry.root.unmount();entry.host.remove();controls.delete(native);}
    }
    for (const native of container.querySelectorAll<HTMLSelectElement>("select:not([data-react-aria-prevent-focus]):not([data-ui-native])")) {
      if (native.closest("[data-ui-owned]")) continue;
      const rows=Array.from(native.options).map((option,i)=>({key:option.value || `__empty_${i}`,value:option.value,label:option.textContent || "",disabled:option.disabled}));
      const label=native.getAttribute("aria-label") || Array.from(native.labels?.[0]?.childNodes ?? []).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(" ").trim() || native.id || t("选择", "Select");
      const signature=JSON.stringify([rows,native.value,native.disabled,native.hidden,label,document.documentElement.lang]);
      let entry=controls.get(native);
      if (!entry) {
        const host=document.createElement("span");host.className="mw-select-host";host.dataset.uiOwned="true";
        native.after(host);native.classList.add("mw-native-select");native.tabIndex=-1;native.setAttribute("aria-hidden","true");
        entry={host,root:createRoot(host),signature:"",restore:watchValue(native)};controls.set(native,entry);
        native.addEventListener("change", schedule);
        native.addEventListener("invalid",event=>{event.preventDefault();host.querySelector<HTMLButtonElement>("button")?.focus();});
      }
      if(entry.signature===signature)continue;
      entry.signature=signature;entry.host.hidden=native.hidden;
      const selected=rows.find(row=>row.value===native.value)?.key ?? null;
      entry.root.render(<Select fullWidth placeholder={t("请选择", "Select an option")} aria-label={translateLabel(label)} value={selected} isDisabled={native.disabled || !rows.length}
        disabledKeys={rows.filter(row=>row.disabled).map(row=>row.key)}
        onChange={key=>{const row=rows.find(row=>row.key===key);if(resetting || !row || native.value===row.value)return;native.value=row.value;native.dispatchEvent(new Event("input",{bubbles:true}));native.dispatchEvent(new Event("change",{bubbles:true}));schedule();}}>
        <Select.Trigger data-native-select={native.id}><Select.Value/><Select.Indicator/></Select.Trigger>
        <Select.Popover className="mw-select-popover" UNSTABLE_portalContainer={native.closest("dialog") ?? undefined}>
          <ListBox aria-label={translateLabel(label)}>{rows.map(row=><ListBox.Item key={row.key} id={row.key} textValue={translateLabel(row.label)}><Label>{translateLabel(row.label)}</Label><ListBox.ItemIndicator/></ListBox.Item>)}</ListBox>
        </Select.Popover>
      </Select>);
    }
  }
  function schedule(){if(!queued){queued=true;queueMicrotask(sync);}}
  const observer=new MutationObserver(records=>{if(records.some(r=>!(r.target instanceof Element?r.target:r.target.parentElement)?.closest("[data-ui-owned]")))schedule();});
  observer.observe(container,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:["disabled","hidden","selected","aria-label"]});
  container.addEventListener("reset",()=>{
    resetting=true;
    queueMicrotask(()=>{resetting=false;schedule();});
  },true);
  subscribe(schedule);sync();
}
