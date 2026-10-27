import React from "react";
import { ArrowRight, ClipboardList, FileSignature, ShieldCheck, GraduationCap, Database } from "lucide-react";

const THEMES = {
  administration: {
    eyebrow: "ADMINISTRATION & OVERSIGHT",
    title: "Project management",
    description: "Coordinate study deliverables, reviews, and site readiness across organizations you are authorized to oversee.",
    sections: [
      {title:"Document coordination",description:"Follow up on contracts and regulatory submissions.",items:[["Contracts","contracts",FileSignature],["Regulatory","regulatory",ShieldCheck]]},
      {title:"Study operations",description:"Review training and data-monitoring workstreams.",items:[["Site Initiation & Training","site-training",GraduationCap],["Data Capture & Monitoring","data-capture",Database]]},
    ],
    attention:"Review your assigned actions and pending approvals in Needs Attention.",
  },
  research: {
    eyebrow: "CLINICAL & RESEARCH TEAM",
    title: "My project work",
    description: "Prepare your site's study deliverables, complete training, and track documents awaiting review.",
    sections: [
      {title:"My site deliverables",description:"Prepare documents and track submission progress.",items:[["Regulatory","regulatory",ShieldCheck],["Contracts","contracts",FileSignature]]},
      {title:"Research readiness",description:"Complete training and manage clinical research data.",items:[["Data Capture & Monitoring","data-capture",Database],["Site Initiation & Training","site-training",GraduationCap]]},
    ],
    attention:"Open Needs Attention to follow up on items requiring action from your account.",
  },
};

export default function ProjectManagement({ experience = "research", siteId, onNavigate }) {
  const view = THEMES[experience] || THEMES.research;
  return <div style={{maxWidth:1180,margin:"0 auto",color:"#213f56"}}>
    <header style={{marginBottom:24}}>
      <span style={{letterSpacing:1.4,fontSize:11,fontWeight:800,color:"#2774a4"}}>{view.eyebrow}</span>
      <h1 style={{fontSize:30,margin:"8px 0"}}>{view.title}</h1>
      <p style={{fontSize:14,color:"#62798c",maxWidth:730}}>{view.description}</p>

    </header>
    <AgileBoard experience={experience} siteId={siteId}/>
    {view.sections.map(section=><section key={section.title} style={{marginBottom:22,padding:20,border:"1px solid #d6e2eb",borderRadius:13,background:"#fff"}}>
      <h2 style={{margin:"0 0 4px",fontSize:18}}>{section.title}</h2>
      <p style={{margin:"0 0 17px",fontSize:13,color:"#6c8292"}}>{section.description}</p>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(225px,1fr))",gap:12}}>
        {section.items.map(([label,page,Icon])=><button key={page} type="button" onClick={()=>onNavigate(page)}
          style={{display:"flex",alignItems:"center",gap:12,textAlign:"left",padding:16,borderRadius:10,border:"1px solid #cfdee8",background:"#f9fcfe",color:"#285a7a",cursor:"pointer"}}>
          <Icon size={19}/><span style={{flex:1,fontSize:13,fontWeight:750}}>{label}</span><ArrowRight size={15}/>
        </button>)}
      </div>
    </section>)}
    <section style={{padding:20,border:"1px solid #c5dae9",borderRadius:13,background:"#eef6fc",display:"flex",gap:14,alignItems:"center",flexWrap:"wrap"}}>
      <ClipboardList size={24}/><div style={{flex:1,minWidth:220}}><strong>Needs Attention</strong><p style={{fontSize:13,margin:"4px 0 0",color:"#546f82"}}>{view.attention}</p></div>
      <button type="button" onClick={()=>onNavigate("needs-attention")} style={{border:0,borderRadius:8,padding:"11px 17px",background:"#236c9f",color:"white",fontWeight:700,cursor:"pointer"}}>Open Needs Attention</button>
    </section>
  </div>;
}


const LANES=[["backlog","Backlog"],["todo","To do"],["in_progress","In progress"],["review","In review"],["done","Done"]];
const TYPES=["Contracts","Regulatory","Project Management","Site Initiation & Training","Data Capture & Monitoring"];
const STORE="atlas.project.tasks.v1";
const stamp=()=>new Date().toISOString();
const event=(type,details)=>({id:Math.random().toString(36).slice(2),type,details,at:stamp(),actor:"Local workspace"});
const buttonStyle={padding:"8px 12px",border:"1px solid #c8d9e6",borderRadius:7,background:"#fff",color:"#215b80",fontWeight:700,cursor:"pointer"};
const inputStyle={padding:"9px 10px",border:"1px solid #cbdbe5",borderRadius:7,width:"100%",boxSizing:"border-box"};
function loadTasks(){try{const rows=JSON.parse(localStorage.getItem(STORE)||"[]");return Array.isArray(rows)?rows.map(x=>({...x,originalDue:x.originalDue??x.due??"",history:Array.isArray(x.history)?x.history:[],extensions:Array.isArray(x.extensions)?x.extensions:[]})):[]}catch{return []}}
function AgileBoard({experience,siteId}){
 const [tasks,setTasks]=React.useState(loadTasks);
 const [view,setView]=React.useState("board");
 const [title,setTitle]=React.useState("");
 const [category,setCategory]=React.useState("Project Management");
 const [assignee,setAssignee]=React.useState("");
 const [due,setDue]=React.useState("");
 const [filter,setFilter]=React.useState("All categories");
 const [range,setRange]=React.useState("active");
 const [selectedId,setSelectedId]=React.useState(null);
 const [requestedDate,setRequestedDate]=React.useState("");
 const [reason,setReason]=React.useState("");
 const [sort,setSort]=React.useState("due");
 React.useEffect(()=>{localStorage.setItem(STORE,JSON.stringify(tasks))},[tasks]);
 const update=(id,patch,type,details)=>setTasks(prev=>prev.map(t=>t.id===id?{...t,...patch,updatedAt:stamp(),history:[...(t.history||[]),event(type,details)]}:t));
 const add=e=>{e.preventDefault();if(!title.trim())return;const created=stamp();setTasks(prev=>[...prev,{id:Math.random().toString(36).slice(2)+Date.now(),title:title.trim(),category,assignee:assignee.trim(),due,originalDue:due,siteId,stage:"backlog",createdAt:created,updatedAt:created,history:[event("created","Task created; original deadline: "+(due||"not set"))],extensions:[]}]);setTitle("");setAssignee("");setDue("")};
 const selected=tasks.find(t=>t.id===selectedId);
 const filtered=tasks.filter(t=>!t.archived&&(filter==="All categories"||t.category===filter));
 const today=new Date().toISOString().slice(0,10);
 const daysLater=new Date(Date.now()+30*86400000).toISOString().slice(0,10);
 const shown=filtered.filter(t=>range==="all"||(range==="active"?t.stage!=="done"&&(t.stage!=="backlog"||!t.due||t.due<=daysLater):range==="upcoming"?Boolean(t.due&&t.due>daysLater):t.stage==="done"));
 const ordered=[...shown].sort((a,b)=>sort==="name"?a.title.localeCompare(b.title):sort==="updated"?(b.updatedAt||b.createdAt||"").localeCompare(a.updatedAt||a.createdAt||""):(a.due||"9999").localeCompare(b.due||"9999"));
 const requestExtension=e=>{e.preventDefault();if(!selected||!requestedDate||!reason.trim())return;const extension={id:Math.random().toString(36).slice(2),oldDue:selected.due||"",newDue:requestedDate,reason:reason.trim(),status:"requested",requestedAt:stamp()};update(selected.id,{extensions:[...(selected.extensions||[]),extension]},"extension_requested","Requested "+(selected.due||"unset")+" → "+requestedDate+"; reason: "+reason.trim());setRequestedDate("");setReason("")};
 const decide=(t,x,approve)=>{const next=(t.extensions||[]).map(ext=>ext.id===x.id?{...ext,status:approve?"approved":"rejected",resolvedAt:stamp()}:ext);update(t.id,{extensions:next,...(approve?{due:x.newDue}:{})},approve?"extension_approved":"extension_rejected",(approve?"Approved":"Declined")+" deadline request "+(x.oldDue||"unset")+" → "+x.newDue+(approve?"; current due date changed":"; current due date retained"))};
 return <section style={{marginTop:25,padding:20,background:"#fff",border:"1px solid #d6e2eb",borderRadius:13}}>
  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:12,marginBottom:13}}>
   <div><h2 style={{fontSize:20,margin:"0 0 5px"}}>Project tasks</h2><p style={{margin:0,fontSize:12,color:"#637d90"}}>Plan a year of deliverables in the register; keep the board focused on actionable work.</p></div>
   <div style={{display:"flex",gap:7}}>{[["board","Agile board"],["register","Task register"]].map(([key,label])=><button type="button" key={key} onClick={()=>{setView(key);setRange(key==="board"?"active":"all")}} style={{...buttonStyle,background:view===key?"#226e9e":"white",color:view===key?"white":"#215b80"}}>{label}</button>)}</div>
  </div>
  <form onSubmit={add} style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(155px,1fr))",gap:10,alignItems:"end",padding:13,background:"#f6f9fc",borderRadius:9,marginBottom:17}}>
   <label style={{fontSize:11,fontWeight:750}}>Task title<input required value={title} onChange={e=>setTitle(e.target.value)} placeholder="New task" style={inputStyle}/></label>
   <label style={{fontSize:11,fontWeight:750}}>Category<select value={category} onChange={e=>setCategory(e.target.value)} style={inputStyle}>{TYPES.map(t=><option key={t}>{t}</option>)}</select></label>
   <label style={{fontSize:11,fontWeight:750}}>Assigned user<input value={assignee} onChange={e=>setAssignee(e.target.value)} placeholder="User ID or name" style={inputStyle}/></label>
   <label style={{fontSize:11,fontWeight:750}}>Original deadline<input type="date" value={due} onChange={e=>setDue(e.target.value)} style={inputStyle}/></label>
   <button type="submit" style={{...buttonStyle,background:"#246fa2",color:"white",height:39}}>Create task</button>
  </form>
  <div style={{display:"flex",flexWrap:"wrap",gap:8,marginBottom:16,alignItems:"center"}}>
   <label style={{fontSize:12}}>Category <select value={filter} onChange={e=>setFilter(e.target.value)} style={{...inputStyle,width:"auto"}}>{["All categories",...TYPES].map(x=><option key={x}>{x}</option>)}</select></label>
   <label style={{fontSize:12}}>Show <select value={range} onChange={e=>setRange(e.target.value)} style={{...inputStyle,width:"auto"}}><option value="active">Active / next 30 days</option><option value="all">All tasks</option><option value="upcoming">Long-term backlog</option><option value="done">Completed</option></select></label>
   {view==="register"&&<label style={{fontSize:12}}>Sort <select value={sort} onChange={e=>setSort(e.target.value)} style={{...inputStyle,width:"auto"}}><option value="due">Deadline</option><option value="name">Task name</option><option value="updated">Last updated</option></select></label>}
   <span style={{marginLeft:"auto",fontSize:12,color:"#61798c"}}>{shown.length} of {filtered.length} tasks</span>
  </div>
  {view==="board"?<div style={{display:"grid",gridTemplateColumns:"repeat(5,minmax(180px,1fr))",gap:10,overflowX:"auto",paddingBottom:6}}>
   {LANES.map(([key,label])=><div key={key} style={{padding:10,background:"#f2f7fa",borderRadius:9,minHeight:140}}>
    <strong style={{fontSize:12}}>{label} ({shown.filter(t=>t.stage===key).length})</strong>
    {shown.filter(t=>t.stage===key).map(t=><button type="button" key={t.id} onClick={()=>setSelectedId(t.id)} style={{display:"block",width:"100%",textAlign:"left",padding:11,marginTop:10,border:"1px solid #d2dfe9",borderRadius:8,background:"white",cursor:"pointer"}}>
     <small style={{color:"#567e9b"}}>{t.category}</small><strong style={{display:"block",fontSize:12,margin:"5px 0"}}>{t.title}</strong><small>{t.assignee||"Unassigned"} · {t.due||"No deadline"}</small>
     {(t.extensions||[]).some(x=>x.status==="requested")&&<div style={{fontSize:10,color:"#9b681f",marginTop:5}}>Deadline change pending</div>}
    </button>)}
   </div>)}
  </div>:<div style={{overflowX:"auto"}}><table style={{width:"100%",borderCollapse:"collapse",fontSize:12,textAlign:"left"}}>
    <thead><tr>{["Task","Category","Assignee","Site","Original due","Current due","Stage","History"].map(x=><th key={x} style={{padding:10,borderBottom:"2px solid #d7e4ed",whiteSpace:"nowrap"}}>{x}</th>)}</tr></thead>
    <tbody>{ordered.map(t=><tr key={t.id}>{[t.title,t.category,t.assignee||"—",t.siteId||"—",t.originalDue||"—",t.due||"—",LANES.find(l=>l[0]===t.stage)?.[1]||t.stage].map((v,i)=><td key={i} style={{padding:10,borderBottom:"1px solid #edf1f5"}}>{v}</td>)}<td style={{borderBottom:"1px solid #edf1f5"}}><button type="button" style={buttonStyle} onClick={()=>setSelectedId(t.id)}>Details</button></td></tr>)}</tbody>
   </table>{!ordered.length&&<p style={{padding:12,color:"#62798c"}}>No tasks match this view.</p>}</div>}
  {selected&&<div role="dialog" aria-label={"Task details for "+selected.title} style={{marginTop:18,padding:18,border:"1px solid #a9cadf",borderRadius:11,background:"#f8fbfe"}}>
    <div style={{display:"flex",justifyContent:"space-between",gap:10,alignItems:"center"}}><div><strong style={{fontSize:17}}>{selected.title}</strong><p style={{fontSize:12,color:"#657e91",margin:"5px 0"}}>{selected.category} · {selected.siteId||"No site"} · {selected.assignee||"Unassigned"}</p></div><button type="button" onClick={()=>setSelectedId(null)} style={buttonStyle}>Close</button></div>
    <div style={{display:"flex",flexWrap:"wrap",gap:20,margin:"15px 0"}}><span><b>Original deadline:</b> {selected.originalDue||"Not set"}</span><span><b>Current deadline:</b> {selected.due||"Not set"}</span></div>
    <label style={{display:"block",fontSize:12,fontWeight:750}}>Task status <select value={selected.stage} onChange={e=>update(selected.id,{stage:e.target.value},"stage_changed","Stage: "+selected.stage+" → "+e.target.value)} style={{...inputStyle,maxWidth:230,marginLeft:8}}>{LANES.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
    <h3 style={{fontSize:15,margin:"19px 0 8px"}}>Request a deadline extension</h3>
    <form onSubmit={requestExtension} style={{display:"grid",gridTemplateColumns:"minmax(150px,190px) minmax(170px,1fr) auto",gap:9,alignItems:"end"}}>
      <label style={{fontSize:11}}>Requested date<input type="date" required min={today} value={requestedDate} onChange={e=>setRequestedDate(e.target.value)} style={inputStyle}/></label>
      <label style={{fontSize:11}}>Reason<input required value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain the delay" style={inputStyle}/></label>
      <button type="submit" style={buttonStyle}>Request extension</button>
    </form>
    {(selected.extensions||[]).length>0&&<div style={{marginTop:13}}>{selected.extensions.map(x=><div key={x.id} style={{padding:10,border:"1px solid #dce8ef",borderRadius:7,marginBottom:6,background:"white",fontSize:12}}>
      <b>{x.oldDue||"Unscheduled"} → {x.newDue}</b> · {x.status}<div style={{color:"#577388"}}>{x.reason}</div>
      {x.status==="requested"&&<div style={{display:"flex",gap:6,marginTop:9}}><button type="button" onClick={()=>decide(selected,x,true)} style={buttonStyle}>Approve new date</button><button type="button" onClick={()=>decide(selected,x,false)} style={buttonStyle}>Decline</button></div>}
    </div>)}</div>}
    <h3 style={{fontSize:15,margin:"18px 0 8px"}}>Task audit history</h3>
    <div style={{display:"grid",gap:6}}>{[...(selected.history||[])].reverse().map((h,i)=><div key={h.id||i} style={{padding:"9px 11px",background:"white",border:"1px solid #e0e9ef",borderRadius:7,fontSize:12}}>
      <strong>{h.type.replaceAll("_"," ")}</strong> · {new Date(h.at).toLocaleString()} <span style={{color:"#698093"}}>· {h.actor}</span><div style={{marginTop:4,color:"#4f697c"}}>{h.details}</div>
    </div>)}</div>
    <button type="button" style={{...buttonStyle,marginTop:16}} onClick={()=>{if(window.confirm("Archive this task? Its audit history will be retained locally.")){update(selected.id,{archived:true},"archived","Task archived");setSelectedId(null)}}}>Archive task</button>
  </div>}
  <p style={{fontSize:11,color:"#71889a",marginTop:18}}>Prototype audit history is stored locally and can be altered or lost with browser data. Extension decisions are simulated and do not represent verified approvals. A centralized append-only server audit trail and authenticated reviewers are required for production.</p>
 </section>;
}
