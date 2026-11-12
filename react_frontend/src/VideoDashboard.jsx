import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Scissors, ShieldCheck, Trash2, Video, GripVertical, RotateCcw, Play, Pause } from "lucide-react";
import "./VideoDashboard.css";
import DictionaryForm, { validateRecordAgainstRules } from "./DictionaryForm";

const bridge = () => window.pywebview?.api;
const id = () => (globalThis.crypto?.randomUUID?.() || String(Date.now()) + Math.random());
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const seconds = value => Number(value || 0).toFixed(2);
const initial = { schema_version: 1, clips: [] };
const normalizePatientId = value => { const text = String(value ?? "").trim(); return /^[0-9]+$/.test(text) ? (text.replace(/^0+(?=\d)/, "") || "0").padStart(3, "0") : text; };

export default function VideoDashboard({ initialSession = null, onCreateClinicalAssessment, onSessionChange }) {
  const [project, setProject] = useState(initialSession?.project || initial);
  const [selected, setSelected] = useState(initialSession?.selected ?? null);
  const [cursor, setCursor] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [maskMode, setMaskMode] = useState(false);
  const dragAnchor = useRef(null);
  const draggedClip = useRef(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [reviewed, setReviewed] = useState(initialSession?.reviewed || false);
  const [step, setStep] = useState(initialSession?.step || 1);
  const [patients, setPatients] = useState([]);
  const [patientsReady, setPatientsReady] = useState(false);
  const [patientId, setPatientId] = useState(initialSession?.patientId || "");
  const [patientRecords, setPatientRecords] = useState(null);
  const [linkedTable, setLinkedTable] = useState(initialSession?.linkedTable || "");
  const [linkedRecordId, setLinkedRecordId] = useState(initialSession?.linkedRecordId || "");
  const [exportRecord, setExportRecord] = useState(null);
  const [outputFolder, setOutputFolder] = useState(initialSession?.outputFolder || "");
  const [videoRules, setVideoRules] = useState(null);
  const [videoMetadata, setVideoMetadata] = useState(initialSession?.videoMetadata || {});
  const [videoFieldErrors, setVideoFieldErrors] = useState({});
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const latestSession = useRef(null);

  // The pipeline settings hold durable paths and edits, not transient preview
  // URLs. Re-register each existing source when the desktop page mounts.
  useEffect(() => {
    let active = true;
    async function restoreSession() {
      try {
        const saved = initialSession || (await bridge()?.video_get_session?.()) || {};
        const incoming = saved.project && Array.isArray(saved.project.clips)
          ? saved.project : initial;
        const clips = await Promise.all(incoming.clips.map(async clip => {
          if (!clip?.path) return null;
          try {
            const previews = await bridge()?.video_register_previews?.([clip.path]);
            const preview = previews?.[0];
            return {...clip, id:clip.id || id(),
              masks:(clip.masks || []).map(mask => ({...mask,id:mask.id || id()})),
              preview_url: preview?.preview_url || clip.preview_url || ""};
          } catch (error) {
            // Keep the remembered selection and edits even if the source has
            // moved. The missing file can be restored at its original path.
            return {...clip, preview_url: "", unavailable: true};
          }
        }));
        if (!active) return;
        const missing = clips.filter(clip => !clip || clip.unavailable).length;
        const restored = {...incoming, clips:clips.filter(Boolean)};
        setProject(restored);
        setSelected(restored.clips.some(clip => clip.id === saved.selected)
          ? saved.selected : restored.clips[0]?.id || null);
        setStep([1,2,3,4].includes(Number(saved.step)) ? Number(saved.step) : 1);
        setPatientId(saved.patientId || "");
        setLinkedTable(saved.linkedTable || "");
        setLinkedRecordId(saved.linkedRecordId || "");
        setOutputFolder(saved.outputFolder || "");
        setVideoMetadata(saved.videoMetadata && typeof saved.videoMetadata === "object"
          ? saved.videoMetadata : {});
        setReviewed(false);
        if (missing) setNotice(
          `${missing} previously selected video file(s) could not be reopened. Check whether the source files were moved or deleted.`
        );
      } catch (error) {
        if (active) setNotice("Could not restore the Video workspace: " + String(error));
      } finally {
        if (active) setSessionLoaded(true);
      }
    }
    restoreSession();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!sessionLoaded) return;
    const snapshot = {
      project, selected, step, patientId, linkedTable, linkedRecordId,
      outputFolder, videoMetadata,
    };
    latestSession.current = snapshot;
    onSessionChange?.(snapshot);
    const timer = setTimeout(() => {
      bridge()?.video_save_session?.(snapshot).catch(error => {
        setNotice("Could not remember Video selections: " + String(error));
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [sessionLoaded, project, selected, step, patientId, linkedTable, linkedRecordId,
      outputFolder, videoMetadata, onSessionChange]);

  // Flush the last snapshot when navigating away, instead of dropping a
  // pending debounce while React unmounts the Video page.
  useEffect(() => () => {
    if (latestSession.current) {
      bridge()?.video_save_session?.(latestSession.current).catch(() => {});
    }
  }, []);

  const normalizedPatientId = normalizePatientId(patientId);
  const existingPatientId = patients.find(p => normalizePatientId(p.patient_id) === normalizedPatientId)?.patient_id || "";
  const newPatient = patientsReady && Boolean(normalizedPatientId) && !existingPatientId;
  const linkedVideoMetadata = {
    ...videoMetadata,
    "CoCANoT Patient ID": existingPatientId,
    "Surgery ID": linkedTable === "Surgical" ? linkedRecordId : "",
    "Recording ID": linkedTable === "Electrophysiology" ? linkedRecordId : "",
    "Image ID": linkedTable === "Imaging" ? linkedRecordId : "",
    "Clinical Assessment ID": patientRecords?.clinical?.[0]?.record_id || "",
  };
  const editableVideoRules = (videoRules || []).filter(rule =>
    !["CoCANoT Patient ID", "Surgery ID", "Recording ID", "Image ID"].includes(rule.field_name)
  );
  useEffect(() => {
    let live = true;
    async function loadPatients() {
      try {
        const siteId = await bridge()?.get_site_id?.();
        if (!siteId) return;
        const rows = await bridge()?.metadata_get_patients?.(siteId);
        if (live) { setPatients(Array.isArray(rows) ? rows : []); setPatientsReady(true); }
      } catch (error) { if (live) { setPatientsReady(false); setNotice("Could not load patient IDs: " + String(error)); } }
    }
    loadPatients();
    return () => { live = false; };
  }, [step]);
  useEffect(() => {
    let active = true;
    setPatientRecords(null);
    if (!existingPatientId || step !== 4) return () => {active=false;};
    async function loadRecords() {
      try {
        const site = await bridge()?.get_site_id?.();
        const result = await bridge()?.metadata_get_patient?.(site,existingPatientId);
        if (active) setPatientRecords(result);
      } catch(e) { if (active) setNotice("Could not load this patient's linked sessions: "+String(e)); }
    }
    loadRecords();
    return () => {active=false;};
  }, [existingPatientId,step]);
  useEffect(() => {
    if (step !== 4) return;
    let active = true;
    async function loadVideoRules() {
      try {
        if (!bridge()?.metadata_get_rules) throw new Error("Metadata rules API is unavailable.");
        const rules = await bridge().metadata_get_rules("Video");
        if (active) setVideoRules(Array.isArray(rules) ? rules : []);
      } catch (error) {
        if (active) { setVideoRules(null); setNotice("Could not load MR Video dictionary: " + String(error)); }
      }
    }
    loadVideoRules();
    return () => { active = false; };
  }, [step]);
  const linkedRecords = linkedTable && patientRecords
    ? patientRecords[linkedTable === "Surgical" ? "surgical" : linkedTable === "Imaging" ? "imaging" : "electrophysiology"] || []
    : [];
  const player = useRef(null);
  const frame = useRef(null);
  const clip = project.clips.find(c => c.id === selected) || project.clips[0];
  const duration = clip ? Math.max(0, clip.end - clip.start) : 0;
  const masks = clip?.masks || [];
  const trackedRegion = (mask, at) => {
    const points = mask.keyframes || [];
    if (!points.length) return mask;
    const fixed = p => ({...mask,
      x:clamp(Number(p.x),0,1-mask.w),y:clamp(Number(p.y),0,1-mask.h),
      w:mask.w,h:mask.h});
    if(at <= points[0].t) return fixed(points[0]);
    for(let i=1;i<points.length;i++) {
      if(at <= points[i].t) {
        const a=points[i-1],b=points[i],factor=(at-a.t)/(b.t-a.t || 1);
        return fixed({x:a.x+(b.x-a.x)*factor,y:a.y+(b.y-a.y)*factor});
      }
    }
    return fixed(points[points.length-1]);
  };
  async function trackMask(mask) {
    const start = Number(mask.start);
    const end = Number(mask.end);
    if(!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > duration || end <= start) {
      setNotice("Set a valid censor start and end before tracking.");
      return;
    }
    if(!bridge()?.video_track_region) {
      setNotice("Motion tracking is unavailable in this desktop build.");
      return;
    }
    try {
      setBusy(true);
      setNotice("");
      // Always initialize tracking from the box geometry at its start time,
      // regardless of the current video playhead position.
      const current = trackedRegion(mask, start);
      const result = await bridge().video_track_region(clip, current, start, end);
      if(!Array.isArray(result?.keyframes) || !result.keyframes.length) {
        throw new Error("Tracking did not produce any positions.");
      }
      mutateClip(c=>({...c,masks:c.masks.map(item=>item.id===mask.id ? {
        ...item,
        keyframes:result.keyframes,
        tracked_until:result.tracked_until,
        tracking_complete:Boolean(result.complete),
        tracking_size_mode:"fixed",
        tracking_message:result.warning || "",
      }:item)}));
      // Tracking results and warnings are displayed beside the censor region.
    } catch(error) {
      setNotice("Tracking failed: " + (error.message || error));
    } finally {
      setBusy(false);
    }
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
    setIsPlaying(false);
  }
  async function addVideos() {
    try {
      if (!bridge()?.video_pick_files) throw new Error("Open this workflow in the CoCANoT desktop application.");
      const response = await bridge().video_pick_files();
      const items = Array.isArray(response) ? response : [];
      if (!items.length) {setNotice("No videos selected.");return;}
      const additions = items.map(m => ({ id:id(), path:m.path, name:m.name, duration:m.duration,
        start:0, end:m.duration, masks:[], remove_audio:false, audio:Boolean(m.audio), width:m.width, height:m.height, preview_url:m.preview_url }));
      setProject(p => ({...p, clips:[...p.clips, ...additions]}));
      setSelected(s => s || additions[0].id);
      setReviewed(false);
      setNotice("");
    } catch (e) { setNotice(String(e.message || e)); }
  }
  function split() {
    if (!clip || cursor <= 0.05 || cursor >= duration - 0.05) return;
    player.current?.pause();
    setIsPlaying(false);
    const splitAt = clip.start + cursor;
    const left = {...clip, end:splitAt, masks:clip.masks.map(m => ({...m, keyframes:[], tracked_until:null, end:Math.min(m.end,cursor)})).filter(m => m.end > m.start)};
    const right = {...clip, id:id(), start:splitAt, masks:clip.masks.map(m => ({...m, keyframes:[], tracked_until:null, start:Math.max(0,m.start-cursor), end:m.end-cursor})).filter(m => m.end > m.start)};
    setProject(p => {const i=p.clips.findIndex(c=>c.id===clip.id); const clips=[...p.clips];clips.splice(i,1,left,right);return {...p,clips};});
    setSelected(right.id); setCursor(0); setReviewed(false);
  }
  function trimClip(side, nextValue) {
    if (!clip) return;
    const oldStart = clip.start;
    const oldEnd = clip.end;
    const next = side === "start"
      ? clamp(Number(nextValue), 0, oldEnd - 0.1)
      : clamp(Number(nextValue), oldStart + 0.1, clip.duration);
    if (!Number.isFinite(next)) return;
    const start = side === "start" ? next : oldStart;
    const end = side === "end" ? next : oldEnd;
    const shift = start - oldStart;
    mutateClip(c => ({...c, start, end,
      masks: c.masks.map(m => ({...m,
        start: clamp(m.start - shift, 0, end - start),
        end: clamp(m.end - shift, 0, end - start),
        keyframes: [], tracked_until: null, tracking_complete: null, tracking_message: ""
      })).filter(m => m.end > m.start)
    }));
    const localTime = clamp(cursor - shift, 0, end - start);
    setCursor(localTime);
    if (player.current) { player.current.pause(); player.current.currentTime = start + localTime; }
  }
  function reorderClip(sourceId, destinationId) {
    if (!sourceId || sourceId === destinationId) return;
    setProject(p => {
      const clips = [...p.clips];
      const from = clips.findIndex(c => c.id === sourceId);
      const to = clips.findIndex(c => c.id === destinationId);
      if (from < 0 || to < 0) return p;
      clips.splice(to, 0, clips.splice(from, 1)[0]);
      return {...p, clips};
    });
    setReviewed(false);
  }
  function move(delta) {
    const index = project.clips.findIndex(c=>c.id===clip?.id);
    const next = index+delta;
    if(index < 0 || next<0 || next>=project.clips.length) return;
    setProject(p=>{const clips=[...p.clips];[clips[index], clips[next]]=[clips[next],clips[index]];return {...p,clips};});
    setReviewed(false);
  }
  function toggleClipPlayback() {
    if (!clip || !player.current || maskMode) return;
    const video = player.current;
    if (!video.paused) { video.pause(); return; }
    if (video.currentTime >= clip.end - 0.05 || video.currentTime < clip.start) {
      video.currentTime = clip.start;
      setCursor(0);
    }
    video.play().catch(() => { setIsPlaying(false); setNotice("Unable to play this video."); });
  }
  function startMaskDrag(event) {
    if (!maskMode || !clip || !frame.current || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    player.current?.pause();
    const rect = frame.current.getBoundingClientRect();
    dragAnchor.current = {
      x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((event.clientY - rect.top) / rect.height, 0, 1)
    };
  }
  function finishMaskDrag(event) {
    if(!maskMode || !clip || !dragAnchor.current || !frame.current) return;
    event.preventDefault();
    event.stopPropagation();
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
  async function pickOutputFolder() {
    try {
      if (!bridge()?.video_pick_output_folder) throw new Error("Output folder picker is unavailable in this desktop build.");
      const folder = await bridge().video_pick_output_folder();
      if (folder) { setOutputFolder(folder); setExportRecord(null); setNotice(""); }
    } catch (error) { setNotice("Could not select output folder: " + String(error.message || error)); }
  }
  async function createClinicalAssessment() {
    if (!normalizedPatientId || busy || !onCreateClinicalAssessment) return;
    try {
      setBusy(true);
      setNotice("");
      let canonicalId = existingPatientId;
      if (!canonicalId) {
        const site = await bridge()?.get_site_id?.();
        if (!site || !bridge()?.metadata_create_patient) throw new Error("Patient registration is unavailable.");
        const result = await bridge().metadata_create_patient(site, normalizedPatientId);
        canonicalId = result?.patient_id || normalizedPatientId;
      }
      onCreateClinicalAssessment(canonicalId, {
        project, selected, step: 4, patientId: canonicalId, outputFolder,
        linkedTable: "", linkedRecordId: "", reviewed: false, videoMetadata
      });
    } catch (error) {
      setNotice("Could not create patient: " + String(error.message || error));
    } finally { setBusy(false); }
  }
  async function exportVideo() {
    if (!project.clips.length) return;
    try {
      if (!bridge()?.video_export_project) throw new Error("Desktop video bridge unavailable.");
      setBusy(true);setNotice("Rendering locally. This can take time for long recordings.");
      if (!outputFolder.trim()) throw new Error("Choose an output folder before exporting.");
      if (!existingPatientId) throw new Error("Enter an existing CoCANoT patient ID or create a Clinical Assessment first.");
      if (!patientRecords?.clinical?.length) throw new Error("A Clinical Assessment is required before exporting video.");
      if (!videoRules) throw new Error("Load the MR Video metadata dictionary before exporting.");
      const invalid = validateRecordAgainstRules(editableVideoRules, linkedVideoMetadata);
      setVideoFieldErrors(invalid);
      if (Object.keys(invalid).length) throw new Error("Complete the required Video metadata fields before exporting.");
      if (linkedTable && (!linkedRecordId || !linkedRecords.some(r => String(r.record_id) === linkedRecordId))) {
        throw new Error("Choose a valid record from the selected category.");
      }
      const result=await bridge().video_export_project(project, existingPatientId, linkedTable, linkedRecordId, outputFolder, linkedVideoMetadata);
      if (result?.error) throw new Error(result.error);
      if (result?.registered && result?.path) {setExportRecord(result);setNotice("");setReviewed(false);}
      else setNotice("Export cancelled.");
    }catch(e){setNotice(String(e.message || e));}finally{setBusy(false);}
  }
  const combinedDuration=useMemo(()=>project.clips.reduce((t,c)=>t+c.end-c.start,0),[project]);
  return <div className="video-workspace">
    <header className="video-header"><h1>Video de-identification</h1></header>
    <nav className="video-steps" aria-label="Video processing steps">
      {["Select Video", "Process Video", "Review", "Export"].map((name,i)=><button type="button" key={name} className={`video-step ${step===i+1?"video-step-active":""}`} aria-current={step===i+1?"step":undefined} disabled={(i>0&&!project.clips.length)||busy} onClick={()=>{setStep(i+1);setMaskMode(false);player.current?.pause();}}>
        <span className="video-step-number">{i+1}</span>
        <span className="video-step-name">{name}</span>
      </button>)}
    </nav>
    {step===1 && <section className="video-panel video-stage">
      <h2>Select Video</h2>
      <div className="video-import-actions">
        <button className="video-primary" onClick={addVideos} disabled={busy}><Plus size={16}/> Add files</button>
        <button onClick={()=>setStep(2)} disabled={busy || project.clips.length===0}>Continue to Process Video</button>
      </div>
      {project.clips.length>0 && <div className="video-import-list" aria-label="Imported recordings">
        <strong>{project.clips.length} recording{project.clips.length===1?"":"s"} selected</strong>
        {project.clips.map(c=><div key={c.id} className="video-import-file">
          <span title={c.name}>{c.name}</span>
          <button type="button" aria-label={`Remove ${c.name}`} title="Remove" disabled={busy}
            onClick={()=>{setProject(p=>({...p,clips:p.clips.filter(x=>x.id!==c.id)}));if(selected===c.id)setSelected(null);setReviewed(false);}}>
            <Trash2 size={15}/>
          </button>
        </div>)}
      </div>}
    </section>}
    {step===2 && <section className="video-panel video-stage"><h2>Process Video</h2></section>}
    {step===3 && <section className="video-panel video-stage"><h2>Review</h2></section>}
    {step===4 && <section className="video-panel video-stage"><h2>Export</h2></section>}
    {step===3 && <CombinedVideoReview clips={project.clips} trackedRegion={trackedRegion} />}
    {step===2 && <div className="video-layout"><section className="video-panel video-preview-panel"><div className="video-panel-title"><Video size={18}/> Preview {clip && <small>{clip.name}</small>}</div>
      <div className="video-player" ref={frame} style={{cursor:maskMode?"crosshair":"pointer"}}>
        {clip ? <><video key={clip.id} ref={player} src={clip.preview_url || ""} playsInline preload="metadata" muted={Boolean(clip.remove_audio)}
          onClick={toggleClipPlayback}
          onLoadedMetadata={event=>{event.currentTarget.currentTime=clip.start;setIsPlaying(false);}}
          onPlay={()=>setIsPlaying(true)} onPause={()=>setIsPlaying(false)}
          onError={()=>setNotice("Video preview could not play this codec. Try an H.264 MP4 recording.")}
          onTimeUpdate={event=>{const video=event.currentTarget;const time=video.currentTime;if(time>=clip.end){video.pause();setCursor(duration);}else{setCursor(clamp(time-clip.start,0,duration));}}}/>
          <div className="video-mask-capture" aria-label="Draw censor region" onMouseDown={startMaskDrag} onMouseUp={finishMaskDrag} onClick={event=>{event.preventDefault();event.stopPropagation();}} style={{pointerEvents:maskMode?"auto":"none",cursor:maskMode?"crosshair":"default"}} />
          <div className="video-mask-overlay">
            {masks.filter(m=>cursor>=m.start && cursor<=m.end).map(m=>{
              const at=trackedRegion(m,cursor);
              return <div key={m.id} className="video-mask" style={{left:`${at.x*100}%`,top:`${at.y*100}%`,width:`${at.w*100}%`,height:`${at.h*100}%`}}/>;
            })}
          </div>
        </> : <div className="video-empty">Import a recording to begin. Original footage is never modified.</div>}
      </div>
      <div className="video-scrub"><button type="button" aria-label={isPlaying?"Pause video":"Play video"} onClick={toggleClipPlayback} disabled={!clip || busy || maskMode}>{isPlaying?<Pause size={16}/>:<Play size={16}/>} {isPlaying?"Pause":"Play"}</button><input type="range" aria-label="Video playhead, also used for Split at playhead" min="0" max={duration||1} step="0.033" value={cursor} disabled={!clip || busy} onChange={e=>{const time=Number(e.target.value);setCursor(time);if(player.current)player.current.currentTime=clip.start+time;}}/><span>{seconds(cursor)} / {seconds(duration)} s</span></div>
      
      
      </section>{step===2 && <aside className="video-panel video-properties"><h2>Editing Tools</h2>{clip ? <>
      <div className="video-edit-action"><strong>Audio</strong><label className="video-audio-option"><input type="checkbox" checked={Boolean(clip.remove_audio)} disabled={busy || clip.audio === false} onChange={e=>mutateClip(c=>({...c,remove_audio:e.target.checked}))}/><span>{clip.audio === false ? "No audio in this clip" : "Remove audio from this clip"}</span></label></div>
      <div className="video-edit-action"><strong>Split clip</strong><button disabled={!clip || busy || cursor <= .05 || cursor >= duration-.05} onClick={split}><Scissors size={16}/> Split at playhead</button></div>
      <div className="video-trim-editor">
        <div className="video-trim-heading"><strong>Trim selected clip</strong><button title="Restore full clip length" disabled={busy || (clip.start===0 && clip.end===clip.duration)} onClick={()=>{const oldStart=clip.start;mutateClip(c=>({...c,start:0,end:c.duration,masks:c.masks.map(m=>({...m,start:m.start+oldStart,end:m.end+oldStart,keyframes:[],tracked_until:null,tracking_complete:null}))}));setCursor(0);if(player.current){player.current.pause();player.current.currentTime=0;}}}><RotateCcw size={14}/> Reset</button></div>
        
        <div className="video-trim-track" aria-hidden="true"><div style={{left:`${clip.start / (clip.duration||1)*100}%`,right:`${(1-clip.end/(clip.duration||1))*100}%`}} /></div>
        <label>Start <strong>{seconds(clip.start)}s</strong><input aria-label="Trim clip start" type="range" min="0" max={Math.max(0,clip.end-.1)} step=".05" value={clip.start} disabled={busy} onChange={e=>trimClip("start",e.target.value)}/></label>
        <label>End <strong>{seconds(clip.end)}s</strong><input aria-label="Trim clip end" type="range" min={Math.min(clip.duration,clip.start+.1)} max={clip.duration} step=".05" value={clip.end} disabled={busy} onChange={e=>trimClip("end",e.target.value)}/></label>
        <div className="video-trim-result">Kept: {seconds(duration)}s of {seconds(clip.duration)}s</div>
      </div>
      <div className="video-edit-action"><strong>Censor boxes</strong><button disabled={!clip || busy} className={maskMode?"video-primary":""} onClick={()=>{player.current?.pause();setMaskMode(v=>!v);}}><ShieldCheck size={16}/> {maskMode?"Drag to draw censor box":"Add censor box"}</button></div>
      <h3>Censor regions ({masks.length})</h3>
      {masks.map((m,i)=><div className="video-mask-settings" key={m.id}><div><strong>Region {i+1}</strong><button aria-label="Remove mask" onClick={()=>mutateClip(c=>({...c,masks:c.masks.filter(x=>x.id!==m.id)}))}><Trash2 size={15}/></button></div>
        <div className="video-actions"><button disabled={busy} onClick={()=>trackMask(m)}>Track censor interval</button></div>
        {m.keyframes?.length>0 && <p role="status">
          <strong>{m.tracking_complete === false || Number(m.tracked_until) < m.end - 0.05 ? "Tracking incomplete" : "Tracking reached the end"}</strong>
          {" · "}{seconds(m.start)}–{seconds(m.tracked_until)}s of {seconds(m.end)}s · {m.keyframes.length} positions · fixed box size.
          {m.tracking_message && <> {m.tracking_message}</>}
        </p>}
        <div className="video-fields">{["x","y","w","h"].map(k=><label key={k}>{k.toUpperCase()} (%)<input type="number" min="0" max="100" step="1" value={Math.round(m[k]*100)} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,keyframes:[],tracked_until:null,tracking_complete:null,tracking_message:"",[k]:clamp(Number(e.target.value)/100,0,k==="x"?1-m.w:k==="y"?1-m.h:k==="w"?1-m.x:1-m.y)}:x)}))}/></label>)}</div>
        <div className="video-fields">{["start","end"].map(k=><label key={k}>{k} (s)<input type="number" step="0.01" min="0" max={duration} value={seconds(m[k])} onChange={e=>mutateClip(c=>({...c,masks:c.masks.map(x=>x.id===m.id?{...x,keyframes:[],tracked_until:null,[k]:clamp(Number(e.target.value),0,duration)}:x)}))}/></label>)}</div>
      </div>)}
      </> : <p>Select a clip to inspect and edit.</p>}</aside>}</div>}
    {step===2 && <section className="video-panel video-timeline">
      <div className="video-panel-title">Timeline <small>{project.clips.length} clips · {seconds(combinedDuration)} seconds</small></div>
      {step===2 && <div className="video-timeline-toolbar"><button onClick={addVideos} disabled={busy}><Plus size={15}/> Add clips</button></div>}
      <div className="video-clips">
        {project.clips.map((c,i)=><div key={c.id} className={`video-clip ${clip?.id===c.id?"video-selected":""}`}
          draggable={!busy && step===2} onDragStart={e=>{draggedClip.current=c.id;e.dataTransfer.effectAllowed="move";e.dataTransfer.setData("text/plain",c.id);}}
          onDragOver={e=>{e.preventDefault();e.dataTransfer.dropEffect="move";}}
          onDrop={e=>{e.preventDefault();const source=draggedClip.current;draggedClip.current=null;reorderClip(source,c.id);}}
          onDragEnd={()=>{draggedClip.current=null;}}
          onClick={()=>selectClip(c)} role="button" tabIndex={0}
          onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectClip(c);}}}>
          <div className="video-clip-art">{step===2 && <GripVertical size={17}/>}<Video size={23}/><span>Clip {i+1}</span></div>
          <strong title={c.name}>{c.name}</strong>
          <small>{seconds(c.end-c.start)}s · {c.masks.length} censor boxes</small>
          {step===2 && <div className="video-clip-buttons"><button title="Remove clip" aria-label={`Remove ${c.name}`} onClick={e=>{e.stopPropagation();setProject(p=>({...p,clips:p.clips.filter(x=>x.id!==c.id)}));if(selected===c.id)setSelected(null);setReviewed(false);}}><Trash2 size={15}/></button></div>}
        </div>)}
        {step===2 && <button className="video-add-tile" onClick={addVideos} disabled={busy}><Plus size={24}/><span>Add another clip</span></button>}
      </div>
      
    </section>}
    {step===4 && <section className="video-panel video-export"><div><label className="video-folder-field"><span>Output folder</span><div className="video-folder-control"><input type="text" aria-label="Output folder" placeholder="Select an output folder" value={outputFolder} onChange={event=>{setOutputFolder(event.target.value);setExportRecord(null);setReviewed(false);}} disabled={busy}/><button type="button" disabled={busy} onClick={pickOutputFolder}>Browse…</button></div></label><label className="video-patient-field">CoCANoT Patient ID <input type="text" list="video-patient-ids" placeholder="Enter CoCANoT Patient ID" value={patientId} onChange={e=>{setPatientId(e.target.value);setLinkedTable("");setLinkedRecordId("");setReviewed(false);setExportRecord(null);}} autoComplete="off" disabled={busy}/><datalist id="video-patient-ids">{patients.map(p=><option key={p.patient_id} value={p.patient_id}/>)}</datalist></label>
      {normalizedPatientId && patientsReady && <div className="video-patient-status">
        {existingPatientId
          ? <>Patient {existingPatientId}{patientRecords?.clinical?.length ? " — Clinical Assessment available" : " — Clinical Assessment required"}</>
          : <>New patient {normalizedPatientId}</>}
        {(!existingPatientId || (patientRecords && !patientRecords.clinical?.length)) &&
          <button type="button" onClick={createClinicalAssessment} disabled={busy || !onCreateClinicalAssessment}>Create Clinical Assessment</button>}
      </div>}
      {existingPatientId && <div className="video-link-fields">
        <label>Link video to
          <select value={linkedTable} disabled={!patientRecords} onChange={e=>{setLinkedTable(e.target.value);setLinkedRecordId("");setReviewed(false);}}>
            <option value="">Patient only (no specific session)</option>
            <option value="Surgical">Surgical record</option>
            <option value="Imaging">Imaging study</option>
            <option value="Electrophysiology">Electrophysiology session</option>
          </select>
        </label>
        {linkedTable && <label>Choose {linkedTable === "Surgical" ? "surgery" : linkedTable === "Imaging" ? "image" : "recording"}
          <select value={linkedRecordId} onChange={e=>{setLinkedRecordId(e.target.value);setReviewed(false);}}>
            <option value="">Choose an existing {linkedTable.toLowerCase()} record…</option>
            {linkedRecords.map(r=><option key={r.record_id} value={String(r.record_id)}>{r.record_id}{r.metadata?.["Surgery ID"] ? " · "+r.metadata["Surgery ID"] : r.metadata?.["Image ID"] ? " · "+r.metadata["Image ID"] : r.metadata?.["Recording ID"] ? " · "+r.metadata["Recording ID"] : ""}</option>)}
          </select>
          {linkedRecords.length===0 && <small>No {linkedTable.toLowerCase()} records exist for this patient. Add one in Patient Data Review or choose patient only.</small>}
        </label>}
      </div>}
      <div className="video-metadata-fields">
        <h2>Video metadata</h2>
        {videoRules === null
          ? <p>Loading Video metadata from the active dictionary…</p>
          : <DictionaryForm
              rules={editableVideoRules}
              values={linkedVideoMetadata}
              errors={videoFieldErrors}
              onChange={(name, value) => {
                setVideoMetadata(current => ({...current, [name]: value}));
                setVideoFieldErrors(current => ({...current, [name]: ""}));
                setReviewed(false);
                setExportRecord(null);
              }}
            />}
      </div><label className="video-checkbox"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> I have reviewed the video and can confirm all PHI has been censored or removed.</label></div><button className="video-primary" onClick={exportVideo} disabled={busy || !clip || !reviewed || !outputFolder.trim() || !existingPatientId || !patientRecords?.clinical?.length || !videoRules || Boolean(linkedTable && !linkedRecordId)}>{busy?"Processing…":"Export to Patient Data Review"}</button></section>}
    {step===4 && exportRecord && <div className="video-notice" role="status"><strong>Video linked to patient {exportRecord.patient_id}</strong><p>Video saved locally: {exportRecord.path}</p>{exportRecord.metadata_path && <p>Metadata JSON saved locally: {exportRecord.metadata_path}</p>}{exportRecord.linked_table && <p>Linked to {exportRecord.linked_table} record {exportRecord.linked_record_id}.</p>}</div>}
    {step>1 && step<4 && <div className="video-stage-navigation"><button onClick={()=>setStep(step-1)}>← Previous step</button><button className="video-primary" onClick={()=>{player.current?.pause();setMaskMode(false);setStep(step+1);}}>Continue →</button></div>}
    {notice && <div className="video-notice" role="status">{notice}</div>}
  </div>;
}

/**
 * Preview the exported sequence using original local preview URLs and saved edits.
 * A single project-wide playhead controls consecutive, trimmed clips.
 * This is a preview, not the rendered export, which still requires final validation.
 */
function CombinedVideoReview({ clips, trackedRegion }) {
  const player = useRef(null);
  const shouldPlay = useRef(false);
  const pendingLocalTime = useRef(0);
  const [clipIndex, setClipIndex] = useState(0);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const segments = useMemo(() => {
    let offset = 0;
    return clips.map((clip) => {
      const length = Math.max(0, Number(clip.end) - Number(clip.start));
      const segment = {clip, offset, length};
      offset += length;
      return segment;
    });
  }, [clips]);
  const total = segments.reduce((sum, segment) => sum + segment.length, 0);
  const active = segments[clipIndex];
  const activeClip = active?.clip;
  const localTime = active ? clamp(position - active.offset, 0, active.length) : 0;

  function stop() {
    shouldPlay.current = false;
    setPlaying(false);
    player.current?.pause();
  }

  function goTo(globalTime, keepPlaying = shouldPlay.current) {
    if (!segments.length) return;
    const nextTime = clamp(Number(globalTime) || 0, 0, total);
    const nextIndex = segments.findIndex((segment, index) =>
      nextTime < segment.offset + segment.length || index === segments.length - 1);
    const index = Math.max(0, nextIndex);
    const segment = segments[index];
    const nextLocal = clamp(nextTime - segment.offset, 0, segment.length);
    pendingLocalTime.current = nextLocal;
    shouldPlay.current = keepPlaying && nextTime < total;
    setPlaying(shouldPlay.current);
    setPosition(nextTime);
    if (index !== clipIndex) {
      setClipIndex(index);
    } else if (player.current) {
      player.current.currentTime = segment.clip.start + nextLocal;
      if (shouldPlay.current) player.current.play().catch(() => { stop(); });
      else player.current.pause();
    }
  }

  function advance() {
    if (clipIndex + 1 >= segments.length) {
      goTo(total, false);
      return;
    }
    goTo(segments[clipIndex + 1].offset, true);
  }

  function updateTime(event) {
    const segment = segments[clipIndex];
    if (!segment) return;
    const videoTime = Number(event.currentTarget.currentTime);
    if (!Number.isFinite(videoTime)) return;
    if (videoTime >= segment.clip.end - 0.035) {
      if (shouldPlay.current) advance();
      else setPosition(segment.offset + segment.length);
      return;
    }
    setPosition(segment.offset + clamp(videoTime - segment.clip.start, 0, segment.length));
  }

  function togglePlayback() {
    if (shouldPlay.current) {
      stop();
      return;
    }
    if (position >= total - 0.035) {
      goTo(0, true);
      return;
    }
    shouldPlay.current = true;
    setPlaying(true);
    if (player.current) player.current.play().catch(() => stop());
  }

  return <section className="video-panel video-combined-review">
    <div className="video-panel-title"><Video size={18}/> Combined video <small>{clips.length} clips · {seconds(total)} seconds</small></div>
    <div className="video-player">
      {activeClip ? <>
        <video key={activeClip.id} ref={player} src={activeClip.preview_url || ""}
          preload="auto" playsInline muted={Boolean(activeClip.remove_audio)}
          onLoadedMetadata={event => {
            const segment = segments[clipIndex];
            if (!segment) return;
            event.currentTarget.currentTime = segment.clip.start + pendingLocalTime.current;
            if (shouldPlay.current) event.currentTarget.play().catch(() => stop());
          }}
          onTimeUpdate={updateTime}
          onEnded={() => { if (shouldPlay.current) advance(); }}
          onError={() => { stop(); setPreviewError("Preview unavailable for this clip. Check the video codec."); }}
          aria-label="Combined video review preview"
        />
        <div className="video-mask-overlay">
          {(activeClip.masks || []).filter(mask => localTime >= mask.start && localTime <= mask.end).map(mask => {
            const region = trackedRegion(mask, localTime);
            return <div className="video-mask" key={mask.id}
              style={{left:`${region.x*100}%`,top:`${region.y*100}%`,width:`${region.w*100}%`,height:`${region.h*100}%`}} />;
          })}
        </div>
      </> : <div className="video-empty">No video selected.</div>}
    </div>
    <div className="video-review-controls">
      <button type="button" onClick={togglePlayback} disabled={!activeClip}>{playing ? <Pause size={16}/> : <Play size={16}/>} {playing ? "Pause" : position >= total ? "Replay" : "Play"}</button>
      <input aria-label="Combined video position" type="range" min="0" max={total || 1}
        step="0.033" value={position} disabled={!activeClip}
        onChange={event => goTo(Number(event.target.value))} />
      <span>{seconds(position)} / {seconds(total)} s</span>
    </div>
    {previewError && <p className="video-review-error" role="alert">{previewError}</p>}
    
  </section>;
}
