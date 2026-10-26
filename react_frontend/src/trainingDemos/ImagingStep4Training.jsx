import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import TutorialSpotlight from "./TutorialSpotlight";

const fields = [
  {name:"descrip",raw:"Patient Name: John Doe",scrubbed:"Patient Name: John Doe",editable:true},
  {name:"aux_file",raw:"Patient001_MRI_2022",scrubbed:"",editable:true},
  {name:"intent_name",raw:"T1 MRI PREOP",scrubbed:"T1 MRI",editable:true},
  {name:"datatype",raw:"16 (FLOAT32)",scrubbed:"16 (FLOAT32)",editable:false},
  {name:"dim",raw:"[3, 176, 256, 256]",scrubbed:"[3, 176, 256, 256]",editable:false},
  {name:"pixdim",raw:"[1, 1, 1, 1]",scrubbed:"[1, 1, 1, 1]",editable:false},
  {name:"qform_code",raw:"1",scrubbed:"1",editable:false},
  {name:"sform_code",raw:"1",scrubbed:"1",editable:false},
];
const stages=[
  {title:"Inspect the extracted NIfTI header",text:"CoCANoT extracts the available header fields and displays their original values beside the scrubbed values. Compare both columns to check for residual identifiers."},
  {title:"Edit a safe header field",text:"The descrip field is selected below. Click the highlighted text box and use your keyboard to remove John Doe from the scrubbed value. Keep a meaningful description such as Patient Name: De-identified MRI. The raw value stays unchanged."},
  {title:"Save the scrubbed header edit",text:"After removing John Doe from the scrubbed description, click Save Header Edit. The raw header remains unchanged; this demonstration saves only in synthetic tutorial state."},
  {title:"Compare raw and PyDeface images",text:"The upper row shows the raw sagittal, coronal and axial slices. The lower row shows the corresponding output from PyDeface. Compare anatomy and facial removal."},
  {title:"Explore rejection and replacement",text:"Click Reject to see three options: exclude the image, put it on hold pending a replacement, or select an external defaced replacement. These are simulated decisions."},
  {title:"Accept the reviewed image",text:"After examining the available rejection choices, use Accept to mark the synthetic image ready for the next step."},
  {title:"Inspect different slices",text:"Drag a sagittal, coronal or axial slider to compare another raw/defaced slice position."},
  {title:"Open linked metadata",text:"Review the CoCANoT patient and imaging identifiers associated with the accepted example image."},
  {title:"Edit linked metadata",text:"Change the synthetic imaging comment to practice correcting linked metadata."},
  {title:"Save linked metadata",text:"Click Save Linked Metadata to keep the example change."},
  {title:"Proceed to Metadata & BIDS",text:"Click the highlighted Continue to Step 5 button. The guide will continue directly—there is no Explore this step detour."},
];
export default function ImagingStep4Training({ImageReview,onComplete,onBack,guided=true}){
  const [stage,setStage]=useState(0);
  const [rows,setRows]=useState(fields);
  const [choice,setChoice]=useState("");
  const [draft,setDraft]=useState("");
  const [headerTyped,setHeaderTyped]=useState(false);
  const [headerSaved,setHeaderSaved]=useState(false);
  const [rejectOpen,setRejectOpen]=useState(false);
  const [rejectionExplored,setRejectionExplored]=useState(false);
  const [decision,setDecision]=useState("");
  const [sliderUsed,setSliderUsed]=useState(false);
  const [metadataOpen,setMetadataOpen]=useState(false);
  const [comment,setComment]=useState("Synthetic preoperative MRI");
  const [metadataSaved,setMetadataSaved]=useState(false);
  const current=stages[stage];
  const safeHeaderEdit = choice === "descrip" && headerTyped && draft.trim().length > 0 && !/john\\s+doe/i.test(draft);
  const targets=["step4-header-table","step4-header-input","step4-save-header","step4-image-viewer","step4-reject","step4-accept","imaging-review-sliders","step4-linked-open","step4-linked-comment","step4-linked-save","imaging-step4-continue"];
  const advance=()=>{ if(stage===0){setChoice("descrip");setDraft(rows.find(row=>row.name==="descrip")?.scrubbed||"");setHeaderTyped(false);} setStage(v=>Math.min(stages.length-1,v+1)); };
  const canProceed= stage===0 || (stage===1&&safeHeaderEdit) || (stage===2&&headerSaved) || stage===3 || (stage===4&&rejectionExplored) || (stage===5&&decision==="Accepted") || (stage===6&&sliderUsed) || (stage===7&&metadataOpen) || (stage===8&&comment!=="Synthetic preoperative MRI") || (stage===9&&metadataSaved);
  function setRejection(value){setDecision(value);setRejectOpen(false);setRejectionExplored(true);}
  return <div style={{display:"grid",gap:18}}>
    {guided && <TutorialSpotlight
      key={`step4-${stage}-${rejectOpen}-${metadataOpen}`}
      enabled
      target={stage===4&&rejectOpen?"step4-reject-options":targets[stage]}
      title={current.title}
      text={current.text}
      step={stage+1}
      totalSteps={stages.length}
      onNext={stage<stages.length-1?advance:undefined}
      nextDisabled={!canProceed}
      nextLabel="Next"
    />}
    <section style={{border:"1px solid #d7e5ef",borderRadius:12,padding:20,background:"white"}}>
      <h3>Raw header versus scrubbed header</h3>
      <p>Example fields extracted from a synthetic NIfTI header. Values here are illustrative, not extracted from the sample volume.</p>
      <div data-tutorial-id="step4-header-table" style={{overflowX:"auto"}}><table style={{width:"100%",borderCollapse:"collapse",textAlign:"left"}}>
        <thead><tr><th>Field</th><th>Raw value</th><th>Scrubbed value</th><th>Editable</th></tr></thead>
        <tbody>{rows.map(row=><tr key={row.name} onClick={()=>{if(row.editable){setChoice(row.name);setDraft(row.scrubbed);setHeaderTyped(false);setHeaderSaved(false);}}} style={{cursor:row.editable?"pointer":"default",background:choice===row.name?"#e9f4fd":"transparent"}}>
          <td style={{padding:10}}>{row.name}</td><td>{row.raw}</td><td>{row.scrubbed||"(removed)"}</td><td>{row.editable?"Yes":"Protected"}</td>
        </tr>)}</tbody>
      </table></div>
      <label style={{display:"grid",gap:7,marginTop:14}}>Scrubbed value for {choice}
        <input data-tutorial-id="step4-header-input" value={draft} onChange={e=>{setDraft(e.target.value);setHeaderTyped(true);setHeaderSaved(false);}} disabled={!rows.find(r=>r.name===choice)?.editable} style={{padding:10,border:"1px solid #aabdcf",borderRadius:7}}/>
      </label>
      {choice === "descrip" && !safeHeaderEdit && <p role="status" style={{fontSize:13,color:"#8b402c"}}>Type a replacement scrubbed value without “John Doe” to enable saving and continue the guide.</p>}
      <button type="button" data-tutorial-id="step4-save-header" disabled={!safeHeaderEdit} onClick={()=>{setRows(old=>old.map(r=>r.name===choice?{...r,scrubbed:draft}:r));setHeaderSaved(true);}} style={{marginTop:12,padding:10,opacity:safeHeaderEdit?1:.5}}>Save Header Edit</button>
      {headerSaved&&<span role="status" style={{marginLeft:12,color:"#267045"}}><Check size={16}/> Example edit saved</span>}
    </section>
    <section style={{border:"1px solid #d7e5ef",borderRadius:12,padding:20,background:"white"}}>
      <h3>Raw versus PyDeface image review</h3>
      <p>Top: raw sagittal, coronal, axial. Bottom: PyDeface output in the same three orientations.</p>
      <div data-tutorial-id="step4-image-viewer" onPointerUp={()=>setSliderUsed(true)} onKeyUp={()=>setSliderUsed(true)}><ImageReview /></div>
      {sliderUsed&&<p style={{color:"#267045"}}>Slice slider interaction recorded.</p>}
    </section>
    <section style={{border:"1px solid #d7e5ef",borderRadius:12,padding:20,background:"white"}}>
      <h3>Review decision</h3>
      <p>Current decision: <strong>{decision||"Pending"}</strong></p>
      <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
        <button type="button" data-tutorial-id="step4-reject" onClick={()=>setRejectOpen(v=>!v)}>Reject / Other options</button>
        <button type="button" data-tutorial-id="step4-accept" onClick={()=>setDecision("Accepted")}>Accept</button>
      </div>
      {rejectOpen&&<div data-tutorial-id="step4-reject-options" style={{display:"grid",gap:10,marginTop:14}}>
        <button type="button" onClick={()=>setRejection("Rejected - Not Included")}>Reject / Do Not Include</button>
        <button type="button" onClick={()=>setRejection("On Hold - Needs Defaced Replacement")}>Put on Hold</button>
        <button type="button" onClick={()=>setRejection("External Replacement Selected (simulated)")}>Upload Replacement (simulation)</button>
        <button type="button" onClick={()=>{setRejectionExplored(true);setRejectOpen(false);}}>Close options without selecting</button>
      </div>}
    </section>
    <section style={{border:"1px solid #d7e5ef",borderRadius:12,padding:20,background:"white"}}>
      <h3>Linked CoCANoT metadata</h3>
      <button type="button" data-tutorial-id="step4-linked-open" onClick={()=>setMetadataOpen(v=>!v)}>{metadataOpen?"Hide":"Review / Edit"} Linked Metadata</button>
      {metadataOpen&&<div style={{marginTop:14,display:"grid",gap:10}}>
        <p>Patient ID: 001 · Imaging ID: 001 · Clinical Assessment ID: 003</p>
        <label data-tutorial-id="step4-linked-comment" style={{display:"grid",gap:7}}>Imaging comment
          <input value={comment} onChange={e=>{setComment(e.target.value);setMetadataSaved(false);}} style={{padding:10,border:"1px solid #aabdcf",borderRadius:7}}/>
        </label>
        <button type="button" data-tutorial-id="step4-linked-save" onClick={()=>setMetadataSaved(true)}>Save Linked Metadata</button>
        {metadataSaved&&<p style={{color:"#267045"}}>Synthetic linked metadata saved.</p>}
      </div>}
    </section>
    <div style={{display:"flex",justifyContent:"space-between",gap:12}}>
      <button type="button" onClick={onBack}>Back to Process</button>
      <button type="button" disabled={guided&&(stage!==stages.length-1||!metadataSaved||decision!=="Accepted")} data-tutorial-id="imaging-step4-continue" onClick={onComplete} style={{padding:"12px 22px",background:"#286c99",border:0,borderRadius:8,color:"white",fontWeight:750}}>Continue to Step 5 <ArrowRight size={16}/></button>
    </div>
  </div>;
}
