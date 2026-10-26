import { useMemo, useState } from "react";
const CHANNELS=["Fp1-F7","F7-T3","T3-T5","T5-O1","Fp2-F8","F8-T4","T4-T6","T6-O2"];
const DURATION=600;
const WINDOW=10;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const secs=v=>Number(v).toFixed(2)+"s";
export default function EphysTrainingSignalViewer({annotations = [],onChooseTime,onChangeWindow,initialOnset = 315}){
 const [start,setStart]=useState(clamp(Number(initialOnset)-5,0,DURATION-WINDOW));
 const [cursor,setCursor]=useState(clamp(Number(initialOnset),0,DURATION));
 const [scale,setScale]=useState(1);
 const paths=useMemo(()=>CHANNELS.map((_,ch)=>{
  const arr=[];for(let i=0;i<=900;i++){const t=start+(i/900)*WINDOW;const v=Math.sin(t*10+ch*2.1)*5+Math.sin(t*22+ch*0.7)*3+Math.sin(t*4+ch)*7;const event=Math.exp(-Math.pow((t-320.7)/0.24,2))*Math.sin(t*44+ch)*22;arr.push((i===0?"M":"L")+i.toFixed(1)+","+(40+ch*65+(v+event)*scale).toFixed(1));}return arr.join(" ");
 }),[start,scale]);
 function seek(t){const v=clamp(t,0,DURATION);setCursor(v);onChooseTime?.(Number(v.toFixed(2)));}
 function move(n){setStart(v=>{const next=clamp(v+n,0,DURATION-WINDOW);onChangeWindow?.(next);return next;});}
 return <section data-tutorial-id="ephys-training-signal" style={{border:"1px solid #cbdde8",borderRadius:12,padding:16,background:"#fff",margin:"16px 0"}}>
  <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
   <div><strong style={{fontSize:16,color:"#173b58"}}>Synthetic EDF signal viewer</strong><p style={{margin:"5px 0",fontSize:12,color:"#617789"}}>8 channels · 10-second window · click the signal to position a new annotation</p></div>
   <div style={{display:"flex",gap:7,alignItems:"center",flexWrap:"wrap"}}>
    <button type="button" onClick={()=>move(-WINDOW)}>← Previous 10s</button><button type="button" onClick={()=>move(WINDOW)}>Next 10s →</button>
    <label style={{fontSize:12}}>Amplitude <select value={scale} onChange={e=>setScale(Number(e.target.value))}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={1.5}>1.5×</option></select></label>
   </div>
  </div>
  <div style={{overflowX:"auto",marginTop:12}}><svg viewBox="0 0 1050 580" role="img" aria-label="Synthetic eight-channel EEG waveform and annotation markers; click to select an onset time" style={{display:"block",width:"100%",minWidth:610,background:"#f8fcff",border:"1px solid #d7e5ef",borderRadius:8,cursor:"crosshair"}} onClick={e=>{const box=e.currentTarget.getBoundingClientRect();const x=(e.clientX-box.left)/box.width*1050;seek(start+clamp((x-125)/900,0,1)*WINDOW);}}>
   {Array.from({length:11},(_,i)=><g key={i}><line x1={125+i*90} x2={125+i*90} y1="15" y2="550" stroke="#e1e9f0"/><text x={125+i*90} y="571" fontSize="11" fill="#617789" textAnchor="middle">{(start+i).toFixed(0)}s</text></g>)}
   {CHANNELS.map((label,i)=><g key={label}><text x="12" y={44+i*65} fontSize="13" fill="#345775">{label}</text><line x1="125" x2="1025" y1={40+i*65} y2={40+i*65} stroke="#dce9f2"/><path d={paths[i]} fill="none" stroke="#265d89" strokeWidth="1.5"/></g>)}
   {annotations.filter(a=>Number(a.onset)>=start&&Number(a.onset)<=start+WINDOW).map((a,i)=>{const x=125+(Number(a.onset)-start)/WINDOW*900;return <g key={i}><line x1={x} x2={x} y1="10" y2="548" stroke="#c26727" strokeWidth="2" strokeDasharray="7 4"/><text x={clamp(x+5,130,850)} y={17+14*(i%3)} fill="#a34b1d" fontSize="12">{a.description||"Annotation"} ({secs(a.onset)})</text></g>})}
   {cursor>=start&&cursor<=start+WINDOW&&<line x1={125+(cursor-start)/WINDOW*900} x2={125+(cursor-start)/WINDOW*900} y1="10" y2="550" stroke="#1d9a68" strokeWidth="2"/>}
  </svg></div>
  <div style={{display:"flex",alignItems:"center",gap:14,marginTop:12,flexWrap:"wrap"}}>
   <label style={{fontSize:12}}>Navigate recording <input aria-label="Recording position" type="range" min="0" max={DURATION-WINDOW} step="1" value={start} onChange={e=>{setStart(Number(e.target.value));onChangeWindow?.(Number(e.target.value));}} style={{width:240,verticalAlign:"middle"}}/></label>
   <span style={{fontSize:12}}>Window {secs(start)}–{secs(start+WINDOW)}</span>
   <span style={{fontSize:12,color:"#176f52"}}>Selected onset: <strong>{secs(cursor)}</strong></span>
   <button type="button" onClick={()=>seek(start+WINDOW/2)}>Use center of current window</button>
  </div>
  <p style={{fontSize:12,color:"#62788b",marginTop:10}}>Demo-only signal, not actual clinical EEG. Orange markers are annotations; green cursor shows where a new annotation will be placed.</p>
 </section>;
}