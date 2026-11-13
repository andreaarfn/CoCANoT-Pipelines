import { useState } from "react";
import "./VideoAnnotations.css";

/**
 * Timeline annotations use seconds relative to the FINAL, trimmed and
 * concatenated video (not the individual original source clips).
 * This component is intentionally shared by Step 4 and Patient Data Review.
 */
export default function VideoAnnotations({
  annotations = [], onChange, duration, position = 0, onSeek,
  disabled = false, onSave, saving = false, message = "",
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [showLabels, setShowLabels] = useState(true);
  const length = Number(duration) || 0;
  const active = annotations.find(a => a.id === selectedId);
  const playable = Number.isFinite(length) && length > 0;
  const mark = a => { if (!disabled) onChange(annotations.map(x => x.id === a.id ? a : x)); };
  function add() {
    if (!playable || disabled) return;
    const onset = Math.min(Math.max(0, position), length);
    const item = {id: globalThis.crypto?.randomUUID?.() || String(Date.now()), onset, duration: Math.min(5, length - onset), description: ""};
    onChange([...annotations, item]);
    setSelectedId(item.id);
  }
  const current = annotations.filter(a => position >= Number(a.onset) && position <= Number(a.onset) + Number(a.duration));
  return <section className="video-annotation-panel" aria-label="Video annotations">
    <div className="video-annotation-heading">
      <div><h3>Annotations</h3><p>Mark events on the final video's timeline. Times reflect trimmed and combined clips.</p></div>
      <button type="button" onClick={add} disabled={!playable || disabled}>+ Add at playhead</button>
    </div>
    <div className="video-annotation-timeline" aria-label="Annotated video timeline">
      {annotations.map(a => <button key={a.id} type="button"
        title={`${a.description || "Event"}: ${a.onset}–${Number(a.onset)+Number(a.duration)}s`}
        aria-label={`Jump to annotation ${a.description || "event"}`}
        className="video-annotation-interval"
        style={{left:`${Math.max(0,Number(a.onset))/Math.max(length,1)*100}%`,width:`${Math.max(0.5,Number(a.duration)/Math.max(length,1)*100)}%`}}
        onClick={()=>{setSelectedId(a.id);onSeek?.(Number(a.onset));}}/>)}
      <div className="video-annotation-playhead" style={{left:`${Math.max(0,Math.min(100,position/Math.max(length,1)*100))}%`}}/>
    </div>
    <div className="video-annotation-controls">
      <label><input type="checkbox" checked={showLabels} onChange={e=>setShowLabels(e.target.checked)}/> Show active events</label>
      <span>{annotations.length} event{annotations.length === 1 ? "" : "s"}</span>
    </div>
    {showLabels && current.length > 0 && <p className="video-annotation-active" role="status">
      At {position.toFixed(2)}s: {current.map(a=>a.description || "Untitled event").join(" · ")}
    </p>}
    {annotations.length === 0 && <p className="video-annotation-empty">No annotations yet. Move the playhead and select Add at playhead.</p>}
    {annotations.map((a,index)=><div className={`video-annotation-entry ${selectedId===a.id?"selected":""}`} key={a.id}>
      <div className="video-annotation-entry-head">
        <button type="button" onClick={()=>{setSelectedId(a.id);onSeek?.(Number(a.onset));}}>Annotation {index+1} · Jump to onset</button>
        <button type="button" disabled={disabled} onClick={()=>{onChange(annotations.filter(x=>x.id!==a.id));if(selectedId===a.id)setSelectedId(null);}}>Remove</button>
      </div>
      <div className="video-annotation-fields">
        <label>Onset (seconds)<input type="number" min="0" max={length} step="any" disabled={disabled}
          value={a.onset} onChange={e=>mark({...a,onset:e.target.value})}/></label>
        <label>Duration (seconds)<input type="number" min="0" step="any" disabled={disabled}
          value={a.duration} onChange={e=>mark({...a,duration:e.target.value})}/></label>
      </div>
      <label>Event description<input type="text" value={a.description} disabled={disabled}
        placeholder="e.g. Clinical seizure — no identifying information"
        onChange={e=>mark({...a,description:e.target.value})}/></label>
    </div>)}
    <p className="video-annotation-note">Avoid names, dates of birth, or other identifying information in descriptions. Annotation edits do not modify video pixels.</p>
    {onSave && <button type="button" disabled={disabled || saving} onClick={onSave}>{saving ? "Saving annotations…" : "Save annotations"}</button>}
    {message && <p role="status">{message}</p>}
  </section>;
}
