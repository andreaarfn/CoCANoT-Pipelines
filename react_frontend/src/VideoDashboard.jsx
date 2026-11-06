import { useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, FolderOpen, Plus, Save, Scissors, ShieldCheck, Trash2, Video } from "lucide-react";
import "./VideoDashboard.css";

const bridge = () => window.pywebview?.api;
const id = () => (globalThis.crypto?.randomUUID?.() || String(Date.now()) + Math.random());
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const seconds = value => Number(value || 0).toFixed(2);
const initial = { schema_version: 1, clips: [] };

export default function VideoDashboard() {
  const [project, setProject] = useState(initial);
  const [selected, setSelected] = useState(null);
  const [cursor, setCursor] = useState(0);
  const [maskMode, setMaskMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const player = useRef(null);
  const frame = useRef(null);
  const clip = project.clips.find(c => c.id === selected) || project.clips[0];
  const duration = clip ? Math.max(0, clip.end - clip.start) : 0;
  const masks = clip?.masks || [];

  function mutateClip(updater) {
    if (!clip) return;
    setProject(current => ({...current, clips: current.clips.map(c => c.id === clip.id ? updater(c) : c)}));
    setReviewed(false);
  }
  function selectClip(c) {
    setSelected(c.id);
    setCursor(0);
    setMaskMode(false);
    if (player.current) player.current.pause();
  }
  async function addVideos() {
    try {
      if (!bridge()?.video_pick_files) throw new Error("Open this workflow in the CoCANoT desktop application.");
      const response = await bridge().video_pick_files();
      const items = Array.isArray(response) ? response : [];
      if (!items.length) return;
      const additions = items.map(m => ({ id:id(), path:m.path, name:m.name, duration:m.duration,
        start:0, end:m.duration, masks:[], width:m.width, height:m.height }));
      setProject(p => ({...p, clips:[...p.clips, ...additions]}));
      setSelected(s => s || additions[0].id);
      setReviewed(false);
      setNotice(`Imported ${additions.length} recording(s).`);
    } catch (e) { setNotice(String(e.message || e)); }
  }
  function split() {
    if (!clip || cursor <= 0.05 || cursor >= duration - 0.05) return;
    const splitAt = clip.start + cursor;
    const left = {...clip, end:splitAt, masks:clip.masks.map(m => ({...m, end:Math.min(m.end,cursor)})).filter(m => m.end > m.start)};
    const right = {...clip, id:id(), start:splitAt, masks:clip.masks.map(m => ({...m, start:Math.max(0,m.start-cursor), end:m.end-cursor})).filter(m => m.end > m.start)};
    setProject(p => {const i=p.clips.findIndex(c=>c.id===clip.id); const clips=[...p.clips];clips.splice(i,1,left,right);return {...p,clips};});
    setSelected(right.id); setCursor(0); setReviewed(false);
  }
  function move(delta) {
    const index = project.clips.findIndex(c=>c.id===clip?.id);
    const next = index+delta;
    if(index < 0 || next<0 || next>=project.clips.length) return;
    setProject(p=>{const clips=[...p.clips];[clips[index], clips[next]]=[clips[next],clips[index]];return {...p,clips};});
    setReviewed(false);
  }
  function addMask(event) {
    if (!maskMode || !clip || !frame.current) return;
    const bounds=frame.current.getBoundingClientRect();
    const x=clamp((event.clientX-bounds.left)/bounds.width,0,0.8);
    const y=clamp((event.clientY-bounds.top)/bounds.height,0,0.8);
    mutateClip(c=>({...c,masks:[...c.masks,{id:id(),type:"solid",x,y,w:0.2,h:0.2,start:cursor,end:duration}]}));
    setMaskMode(false);
  }
  async function projectAction(action) {
    try {
      if (!bridge()?.[action]) throw new Error("Desktop video bridge unavailable.");
      setBusy(true);setNotice("");
      const result = await bridge()[action](action==="video_save_project" ? project : undefined);
      if (action==="video_load_project" && result) {
        const loaded={...result,clips:result.clips.map(c=>({...c,id:c.id || id(),masks:(c.masks || []).map(m=>({...m,id:m.id || id()}))}))};
        setProject(loaded);setSelected(loaded.clips[0]?.id||null);setCursor(0);setReviewed(false);
      }
      if (result?.error) throw new Error(result.error);
      if (result) setNotice(action==="video_save_project" ? "Project saved." : action==="video_load_project" ? "Project opened." : String(result?.path || "Complete."));
    } catch(e){setNotice(String(e.message || e));}finally{setBusy(false);}
  }
  async function exportVideo() {
    if (!project.clips.length) return;
    try {
      if (!bridge()?.video_export_project) throw new Error("Desktop video bridge unavailable.");
      setBusy(true);setNotice("Rendering locally. This can take time for long recordings.");
      const result=await bridge().video_export_project(project);
      if (result?.error) throw new Error(result.error);
      if (result?.path) {setNotice("Export complete: " + result.path + ". Review the rendered MP4 before sharing.");setReviewed(false);}
      else setNotice("Export cancelled.");
    }catch(e){setNotice(String(e.message || e));}finally{setBusy(false);}
  }
  const combinedDuration=useMemo(()=>project.clips.reduce((t,c)=>t+c.end-c.start,0),[project]);
  return <div className="video-workspace">
    <header className="video-header"><div><div className="video-eyebrow">COCANOT PIPELINES / VIDEO</div><h1>Video de-identification</h1><p>Non-destructive editing and opaque masking. Processing stays on your device.</p></div>
      <div className="video-actions"><button onClick={addVideos} disabled={busy}><Plus size={16}/> Import video</button><button onClick={()=>projectAction("video_load_project")} disabled={busy}><FolderOpen size={16}/> Open project</button><button onClick={()=>projectAction("video_save_project")} disabled={busy || !clip}><Save size={16}/> Save project</button></div></header>
    <div className="video-steps"><span>1 · Import</span><span>2 · Edit</span><span>3 · Censor</span><span>4 · Review</span><span>5 · Export</span></div>
    <div className="video-layout"><section className="video-panel video-preview-panel"><div className="video-panel-title"><Video size={18}/> Preview {clip && <small>{clip.name}</small>}</div>
      <div className="video-player" ref={frame} onClick={addMask} style={{cursor:maskMode?"crosshair":"default"}}>
        {clip ? <><video key={clip.id} ref={player} src={`file://${clip.path}`} controls onLoadedMetadata={event=>{event.currentTarget.currentTime=clip.start;}}
          onTimeUpdate={event=>{const time=event.currentTarget.currentTime;if(time >=clip.end){event.currentTarget.pause();}setCursor(clamp(time-clip.start,0,duration));}}/>
          <div className="video-mask-overlay">{masks.filter(m=>cursor>=m.start && cursor<=m.end).map(m=><div key={m.id} className="video-mask" style={{left:`${m.x*100}%`,top:`${m.y*100}%`,width:`${m.w*100}%`,height:`${m.h*100}%`}}/>)}</div>
        </> : <div className="video-empty">Import a recording to begin. Original footage is never modified.</div>}
      </div>
      <div className="video-scrub"><input type="range" min="0" max={duration||1} step="0.033" value={cursor} disabled={!clip} onChange={e=>{const time=Number(e.target.value);setCursor(time);if(player.current)player.current.currentTime=clip.start+time;}}/><span>{seconds(cursor)} / {seconds(duration)} s</span></div>
      <div className="video-actions"><button disabled={!clip || busy} onClick={split}><Scissors size={16}/> Split at playhead</button><button disabled={!clip || busy} className={maskMode?"video-primary":""} onClick={()=>setMaskMode(v=>!v)}><ShieldCheck size={16}/> {maskMode?"Click preview to place mask":"Add censor box"}</button></div>
      <p className="video-hint">Censor boxes are solid black. Preview overlays are guides; inspect the rendered file before releasing it. Audio is removed from exports.</p>
      </section><aside className="video-panel video-properties"><h2>Clip and censor settings</h2>{clip ? <>
      <label>Start (seconds)<input type="number" step="0.01" min="0" max={clip.end-0.01} value={clip.start} onChange={e=>mutateClip(c=>({...c,start:clamp(Number(e.target.value),0,c.end-0.01)}))}/></label>
      <label>End (seconds)<input type="number" step="0.01" min={clip.start+0.01} max={clip.duration} value={clip.end} onChange={e=>mutateClip(c=>({...c,end:clamp(Number(e.target.value),c.start+0.01,c.duration)}))}/></label>
      <h3>Censor regions ({masks.length})</h3>{!masks.length && <p>No masks on this clip.</p>}
      {masks.map((m,i)=><div className="video-mask-settings" key={m.id}><div><strong>Region {i+1}</strong><button aria-label="Remove mask" onClick={()=>mutateClip(c=>({...c,masks:c.masks.filter(x=>x.id!==m.id)}))}><Trash2 size={15}/></button></div>
        <div className="video-fields">{["x","y","w","h"].map(k=><label key={k}>{k.toUpperCase()} (%)<input type="number" min="0" max="100" step="1" value={Math.round(m[k]*100)} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,[k]:clamp(Number(e.target.value)/100,0,k==="x"?1-m.w:k==="y"?1-m.h:k==="w"?1-m.x:1-m.y)}:x)}))}/></label>)}</div>
        <div className="video-fields">{["start","end"].map(k=><label key={k}>{k} (s)<input type="number" step="0.01" min="0" max={duration} value={seconds(m[k])} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,[k]:clamp(Number(e.target.value),0,duration)}:x)}))}/></label>)}</div>
      </div>)}
      </> : <p>Select a clip to inspect and edit.</p>}</aside></div>
    <section className="video-panel video-timeline"><div className="video-panel-title">Timeline <small>{project.clips.length} clip(s) · {seconds(combinedDuration)} seconds</small></div><div className="video-clips">{project.clips.map((c,i)=><div key={c.id} className={`video-clip ${clip?.id===c.id?"video-selected":""}`} onClick={()=>selectClip(c)}>
      <span>{i+1}. {c.name}</span><small>{seconds(c.end-c.start)}s · {c.masks.length} masks</small><div className="video-clip-buttons"><button title="Move left" disabled={i===0} onClick={e=>{e.stopPropagation();setSelected(c.id);setProject(p=>{const a=[...p.clips];[a[i-1],a[i]]=[a[i],a[i-1]];return {...p,clips:a};});setReviewed(false);}}><ArrowUp size={15}/></button><button title="Move right" disabled={i===project.clips.length-1} onClick={e=>{e.stopPropagation();setSelected(c.id);setProject(p=>{const a=[...p.clips];[a[i+1],a[i]]=[a[i],a[i+1]];return {...p,clips:a};});setReviewed(false);}}><ArrowDown size={15}/></button><button title="Remove clip" onClick={e=>{e.stopPropagation();setProject(p=>({...p,clips:p.clips.filter(x=>x.id!==c.id)}));if(selected===c.id)setSelected(null);setReviewed(false);}}><Trash2 size={15}/></button></div></div>)}</div></section>
    <section className="video-panel video-export"><div><h2>Review & export</h2><p>Export creates a 720p MP4 with opaque censor regions and no audio. This workflow does not automatically detect identifiers or validate privacy.</p><label className="video-checkbox"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> I have reviewed the censor positions and time intervals.</label></div><button className="video-primary" onClick={exportVideo} disabled={busy || !clip || !reviewed}>{busy?"Processing…":"Export censored MP4"}</button></section>
    {notice && <div className="video-notice" role="status">{notice}</div>}
  </div>;
}
