import {useEffect, useState, useSyncExternalStore} from "react";
import {createRoot} from "react-dom/client";
import {Button, Drawer, Tooltip} from "@heroui/react";
import {Moon, Sun, Monitor, Languages, PanelLeftClose, Menu, Orbit, SlidersHorizontal, AudioLines, PersonStanding, Glasses, ArrowUpRight} from "lucide-react";
import {getLanguage, getTheme, setLanguage, setTheme, subscribe, t} from "./preferences";
import {enhanceStudio} from "./legacy";
import {enhanceSelects} from "./selects";
import "./theme.css";

const workspaces = [
  {id:"setup", name:"Set Up", zh:"部署", href:"./setup.html", Icon:SlidersHorizontal},
  {id:"motion", name:"Motion Lab", zh:"动作实验室", href:"./", Icon:AudioLines},
  {id:"character", name:"Character Studio", zh:"角色工作室", href:"./character.html", Icon:PersonStanding},
  {id:"vrchat", name:"VRChat Studio", zh:"VRChat 工作室", href:"./vrchat.html", Icon:Glasses},
];
export function usePreferences() {
  useSyncExternalStore(subscribe, () => `${getLanguage()}:${getTheme()}`);
}
function Chrome({page}:{page:string}) {
  usePreferences();
  const language = getLanguage();
  useEffect(() => {
    const workspace = workspaces.find(item => item.id === page);
    if (workspace) document.title = `VIREA · ${t(workspace.zh, workspace.name)}`;
  }, [page, language]);
  const [open, setOpen] = useState(false);
  const theme = getTheme();
  const ThemeIcon = theme === "system" ? Monitor : theme === "light" ? Sun : Moon;
  const links = <nav aria-label={t("工作台导航", "Workspace navigation")}>
    {workspaces.map(({id,name,zh,href,Icon}) => <a key={id} href={href} aria-current={page === id ? "page" : undefined}><Icon size={17}/><span>{t(zh,name)}</span></a>)}
  </nav>;
  return <header className="mw-chrome">
    <div className="mw-identity"><Drawer><Button isIconOnly variant="ghost" className="mw-menu" aria-label={t("打开导航", "Open navigation")} onPress={() => setOpen(true)}><Menu size={20}/></Button>
      <Drawer.Backdrop isOpen={open} onOpenChange={setOpen}><Drawer.Content placement="left"><Drawer.Dialog className="mw-navigation"><Drawer.CloseTrigger aria-label={t("关闭导航","Close navigation")}/><Drawer.Header><Drawer.Heading>VIREA</Drawer.Heading></Drawer.Header><Drawer.Body>{links}</Drawer.Body></Drawer.Dialog></Drawer.Content></Drawer.Backdrop></Drawer>
      <a href="./" className="mw-logo" aria-label="VIREA"><Orbit size={25}/><strong>VIREA</strong><span>MOONWEAVE AI</span></a>
    </div>
    <div className="mw-desktop-nav">{links}</div>
    <div className="mw-preferences">
      <Tooltip><Button variant="ghost" onPress={() => setLanguage(getLanguage() === "en" ? "zh-CN" : "en")} aria-label={t("切换为英语", "Switch to Chinese")}><Languages size={17}/><span>{getLanguage() === "en" ? "EN" : "中文"}</span></Button><Tooltip.Content>{t("语言：简体中文", "Language: English")}</Tooltip.Content></Tooltip>
      <Tooltip><Button variant="ghost" isIconOnly aria-label={t(`外观：${theme === "system" ? "跟随系统" : theme === "light" ? "浅色" : "深色"}`, `Appearance: ${theme}`)} onPress={() => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system")}><ThemeIcon size={18}/></Button><Tooltip.Content>{t("浅色 / 深色 / 跟随系统", "Light / Dark / System")}</Tooltip.Content></Tooltip>
      <a className="mw-docs" href="https://github.com/Moonweave-AI/virea/tree/main/doc" target="_blank" rel="noreferrer" aria-label={t("文档", "Documentation")}><ArrowUpRight size={18}/></a>
    </div>
  </header>;
}

export function mountStudioChrome(page: string, root: HTMLElement) {
  document.body.dataset.studio = page;
  const host = document.createElement("div"); host.id = "studio-chrome"; document.body.prepend(host);
  createRoot(host).render(<Chrome page={page}/>);
  enhanceStudio(root);
  enhanceSelects(root);
}

export {PanelLeftClose};
