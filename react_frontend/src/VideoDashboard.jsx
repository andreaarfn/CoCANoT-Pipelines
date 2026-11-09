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
  const dragAnchor = useRef(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const player = useRef(null);
  const frame = useRef(null);
  const clip = project.clips.find(c => c.id === selected) || project.clips[0];
  const duration = clip ? Math.max(0, clip.end - clip.start) : 0;
  const masks = clip?.masks || [];
  const blur = clip?.background_blur || {enabled:false,x:0.25,y:0.25,w:0.5,h:0.5};
  const trackedRegion = (mask, at) => {
    const points = mask.keyframes || [];
    if (!points.length) return mask;
    if (at <= points[0].t) return {...mask,...points[0]};
    for(let i=1;i<points.length;i++) {
      if(at <= points[i].t) {
        const a=points[i-1],b=points[i],factor=(at-a.t)/(b.t-a.t || 1);
        return {...mask,...Object.fromEntries(["x","y","w","h"].map(k=>[k,a[k]+(b[k]-a[k])*factor]))};
      }
    }
    return {...mask,...points[points.length-1]};
  };
  async function trackMask(mask) {
    if(mask.end <= mask.start + 0.05) {setNotice("Increase the mask time interval before tracking.");return;}
    if(!bridge()?.video_track_region) {setNotice("Motion tracking is unavailable in this desktop build.");return;}
    try {
      setBusy(true);setNotice("Tracking locally. The tracker stops when confidence drops.");
      const start = Math.max(0, Math.min(cursor, mask.end-0.05, duration-0.05));
      const current = trackedRegion(mask,start);
      const result = await bridge().video_track_region(clip, current, start);
      mutateClip(c=>({...c,masks:c.masks.map(item=>item.id===mask.id?{
        ...item,...current,keyframes:result.keyframes,
        tracked_until:result.tracked_until,
        start:start
      }:item)}));
      setNotice(result.warning || "Motion tracking completed. Review tracked censor box at multiple points before export.");
    }catch(error){setNotice("Tracking failed: " + (error.message || error));}finally{setBusy(false);}
  }

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
      if (!items.length) {setNotice("No videos selected.");return;}
      const additions = items.map(m => ({ id:id(), path:m.path, name:m.name, duration:m.duration,
        start:0, end:m.duration, masks:[], width:m.width, height:m.height, preview_url:m.preview_url }));
      setProject(p => ({...p, clips:[...p.clips, ...additions]}));
      setSelected(s => s || additions[0].id);
      setReviewed(false);
      setNotice(`Imported ${additions.length} recording(s).`);
    } catch (e) { setNotice(String(e.message || e)); }
  }
  function split() {
    if (!clip || cursor <= 0.05 || cursor >= duration - 0.05) return;
    const splitAt = clip.start + cursor;
    const left = {...clip, end:splitAt, masks:clip.masks.map(m => ({...m, keyframes:[], tracked_until:null, end:Math.min(m.end,cursor)})).filter(m => m.end > m.start)};
    const right = {...clip, id:id(), start:splitAt, masks:clip.masks.map(m => ({...m, keyframes:[], tracked_until:null, start:Math.max(0,m.start-cursor), end:m.end-cursor})).filter(m => m.end > m.start)};
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
  function editBlur(key,value) {
    mutateClip(c=>({...c,background_blur:{...{enabled:false,x:0.25,y:0.25,w:0.5,h:0.5},...(c.background_blur || {}),[key]:value}}));
  }
  function startMaskDrag(event) {
    if (!maskMode || !clip || !frame.current || event.button !== 0) return;
    const rect = frame.current.getBoundingClientRect();
    dragAnchor.current = {
      x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((event.clientY - rect.top) / rect.height, 0, 1)
    };
  }
  function finishMaskDrag(event) {
    if(!maskMode || !clip || !dragAnchor.current || !frame.current) return;
    const bounds=frame.current.getBoundingClientRect();
    const point={x:clamp((event.clientX-bounds.left)/bounds.width,0,1),
                 y:clamp((event.clientY-bounds.top)/bounds.height,0,1)};
    const anchor=dragAnchor.current;
    dragAnchor.current=null;
    let x=Math.min(point.x,anchor.x), y=Math.min(point.y,anchor.y);
    let w=Math.abs(point.x-anchor.x),h=Math.abs(point.y-anchor.y);
    if(w<0.025 || h<0.025) {
      x=clamp(point.x-0.1,0,0.8);y=clamp(point.y-0.1,0,0.8);
      w=0.2;h=0.2;
    }
    mutateClip(c=>({...c,masks:[...c.masks,{id:id(),type:"solid",x,y,w,h,start:cursor,end:duration}]}));
    setMaskMode(false);
  }
  async function projectAction(action) {
    try {
      if (!bridge()?.[action]) throw new Error("Desktop video bridge unavailable.");
      setBusy(true);setNotice("");
      const result = await bridge()[action](action==="video_save_project" ? project : undefined);
      if (action==="video_load_project" && result?.clips) {
        const previews = await bridge().video_register_previews(result.clips.map(c => c.path));
        const previewByPath = new Map(previews.map(item => [item.path, item.preview_url]));
        result.clips = result.clips.map(c => ({...c,preview_url:previewByPath.get(c.path)}));
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
      <div className="video-player" ref={frame} onMouseDown={startMaskDrag} onMouseUp={finishMaskDrag} style={{cursor:maskMode?"crosshair":"default"}}>
        {clip ? <><video key={clip.id} ref={player} src={clip.preview_url || ""} controls onLoadedMetadata={event=>{event.currentTarget.currentTime=clip.start;}} onError={()=>setNotice("Video preview could not play this codec. Try an H.264 MP4 recording.")}
          onTimeUpdate={event=>{const time=event.currentTarget.currentTime;if(time >=clip.end){event.currentTarget.pause();}setCursor(clamp(time-clip.start,0,duration));}}/>
          <div className="video-mask-overlay">
            {blur.enabled && <>
              <div className="video-blurred-area" style={{left:0,top:0,width:"100%",height:`${blur.y*100}%`}} />
              <div className="video-blurred-area" style={{left:0,top:`${(blur.y+blur.h)*100}%`,width:"100%",height:`${(1-blur.y-blur.h)*100}%`}} />
              <div className="video-blurred-area" style={{left:0,top:`${blur.y*100}%`,width:`${blur.x*100}%`,height:`${blur.h*100}%`}} />
              <div className="video-blurred-area" style={{left:`${(blur.x+blur.w)*100}%`,top:`${blur.y*100}%`,width:`${(1-blur.x-blur.w)*100}%`,height:`${blur.h*100}%`}} />
              <div className="video-preserve-outline" style={{left:`${blur.x*100}%`,top:`${blur.y*100}%`,width:`${blur.w*100}%`,height:`${blur.h*100}%`}} />
            </>}
            {masks.filter(m=>cursor>=m.start && cursor<=m.end).map(m=>{
              const at=trackedRegion(m,cursor);
              return <div key={m.id} className="video-mask" style={{left:`${at.x*100}%`,top:`${at.y*100}%`,width:`${at.w*100}%`,height:`${at.h*100}%`}}/>;
            })}
          </div>
        </> : <div className="video-empty">Import a recording to begin. Original footage is never modified.</div>}
      </div>
      <div className="video-scrub"><input type="range" min="0" max={duration||1} step="0.033" value={cursor} disabled={!clip} onChange={e=>{const time=Number(e.target.value);setCursor(time);if(player.current)player.current.currentTime=clip.start+time;}}/><span>{seconds(cursor)} / {seconds(duration)} s</span></div>
      <div className="video-actions"><button disabled={!clip || busy} onClick={split}><Scissors size={16}/> Split at playhead</button><button disabled={!clip || busy} className={maskMode?"video-primary":""} onClick={()=>setMaskMode(v=>!v)}><ShieldCheck size={16}/> {maskMode?"Drag to draw censor box":"Add censor box"}</button></div>
      <p className="video-hint">Censor boxes are solid black. Tracking is approximate; inspect the rendered file before releasing it. Audio is removed from exports.</p>
      </section><aside className="video-panel video-properties"><h2>Clip and censor settings</h2>{clip ? <>
      <label>Start (seconds)<input type="number" step="0.01" min="0" max={clip.end-0.01} value={clip.start} onChange={e=>mutateClip(c=>({...c,start:clamp(Number(e.target.value),0,c.end-0.01)}))}/></label>
      <label>End (seconds)<input type="number" step="0.01" min={clip.start+0.01} max={clip.duration} value={clip.end} onChange={e=>mutateClip(c=>({...c,end:clamp(Number(e.target.value),c.start+0.01,c.duration)}))}/></label>
      <h3>Background blur</h3>
      <label className="video-checkbox"><input type="checkbox" checked={Boolean(blur.enabled)} onChange={e=>editBlur("enabled",e.target.checked)}/> Blur outside preserved area</label>
      {blur.enabled && <>
        <label>Blur method<select value={blur.mode || "rectangle"} onChange={e=>editBlur("mode",e.target.value)}>
          <option value="rectangle">Preserve rectangle</option>
          <option value="subject">Smart subject selection (GrabCut)</option>
        </select></label>
        <p>{blur.mode === "subject"
          ? "The selected rectangle seeds pixel-level segmentation when exporting. The editor only shows an approximate preview; inspect the final output."
          : "Keep the rectangle sharp and blur the remaining background. Blur alone is not validated de-identification."}</p>
        <div className="video-fields">{["x","y","w","h"].map(k=><label key={k}>Preserve {k.toUpperCase()} (%)<input type="number" min="0" max="100" step="1" value={Math.round(blur[k]*100)} onChange={e=>editBlur(k,clamp(Number(e.target.value)/100,0,k==="x"?1-blur.w:k==="y"?1-blur.h:k==="w"?1-blur.x:1-blur.y))}/></label>)}</div>
      </>}
      <h3>Censor regions ({masks.length})</h3>{!masks.length && <p>No masks on this clip.</p>}
      {masks.map((m,i)=><div className="video-mask-settings" key={m.id}><div><strong>Region {i+1}</strong><button aria-label="Remove mask" onClick={()=>mutateClip(c=>({...c,masks:c.masks.filter(x=>x.id!==m.id)}))}><Trash2 size={15}/></button></div>
        <div className="video-actions"><button disabled={busy} onClick={()=>trackMask(m)}>Track forward from playhead</button></div>
        {m.keyframes?.length>0 && <p>Tracked to {seconds(m.tracked_until)}s · {m.keyframes.length} keyframes. Verify alignment throughout the clip.</p>}
        <div className="video-fields">{["x","y","w","h"].map(k=><label key={k}>{k.toUpperCase()} (%)<input type="number" min="0" max="100" step="1" value={Math.round(m[k]*100)} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,keyframes:[],tracked_until:null,[k]:clamp(Number(e.target.value)/100,0,k==="x"?1-m.w:k==="y"?1-m.h:k==="w"?1-m.x:1-m.y)}:x)}))}/></label>)}</div>
        <div className="video-fields">{["start","end"].map(k=><label key={k}>{k} (s)<input type="number" step="0.01" min="0" max={duration} value={seconds(m[k])} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,[k]:clamp(Number(e.target.value),0,duration)}:x)}))}/></label>)}</div>
      </div>)}
      </> : <p>Select a clip to inspect and edit.</p>}</aside></div>
    <section className="video-panel video-timeline"><div className="video-panel-title">Timeline <small>{project.clips.length} clip(s) · {seconds(combinedDuration)} seconds</small></div><div className="video-clips">{project.clips.map((c,i)=><div key={c.id} className={`video-clip ${clip?.id===c.id?"video-selected":""}`} onClick={()=>selectClip(c)}>
      <span>{i+1}. {c.name}</span><small>{seconds(c.end-c.start)}s · {c.masks.length} masks</small><div className="video-clip-buttons"><button title="Move left" disabled={i===0} onClick={e=>{e.stopPropagation();setSelected(c.id);setProject(p=>{const a=[...p.clips];[a[i-1],a[i]]=[a[i],a[i-1]];return {...p,clips:a};});setReviewed(false);}}><ArrowUp size={15}/></button><button title="Move right" disabled={i===project.clips.length-1} onClick={e=>{e.stopPropagation();setSelected(c.id);setProject(p=>{const a=[...p.clips];[a[i+1],a[i]]=[a[i],a[i+1]];return {...p,clips:a};});setReviewed(false);}}><ArrowDown size={15}/></button><button title="Remove clip" onClick={e=>{e.stopPropagation();setProject(p=>({...p,clips:p.clips.filter(x=>x.id!==c.id)}));if(selected===c.id)setSelected(null);setReviewed(false);}}><Trash2 size={15}/></button></div></div>)}</div></section>
    <section className="video-panel video-export"><div><h2>Review & export</h2><p>Export creates a 720p MP4 with moving censor regions and optional background blur; audio is removed. Tracking is fallible and does not validate privacy.</p><label className="video-checkbox"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> I have reviewed the censor positions and time intervals.</label></div><button className="video-primary" onClick={exportVideo} disabled={busy || !clip || !reviewed}>{busy?"Processing…":"Export censored MP4"}</button></section>
    {notice && <div className="video-notice" role="status">{notice}</div>}
  </div>;
}
