import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Check, CheckCircle2, ChevronRight, FilePlus2, FileText, Layers2, Play, Plus, Settings2, ShieldCheck, Trash2 } from 'lucide-react';
import { api, downloadText } from './api';
import { SheetViewer } from './SheetViewer';
import { OrderEditor } from './OrderEditor';
import { Busy, ErrorNotice, Field, Modal } from './ui';
import { formatNumber, geometryPath } from './geometry';
import type { Order, PipelineResult, ProcessSettings, Remnant, Upload } from './types';

const initialSettings: ProcessSettings = {machine_profile:'ISO_6983_GRBL',allow_demo_stock:false,lead_in_radius_mm:0,cut_feedrate_mm_min:1800,laser_power_s:1000,pierce_delay_sec:.4};
export function batchIsComplete(result: PipelineResult): boolean {
  const used = result.nesting.sheet_outcomes.filter(s => s.placed_parts.length > 0);
  return result.nesting.total_requested > 0 && result.nesting.total_placed === result.nesting.total_requested
    && result.nesting.sanitizer_verified && used.length > 0
    && used.every(sheet => result.gcode_programs.some(p => p.sheet_id === sheet.sheet_id && p.verification.verified_safe));
}
interface Props { inventory: Remnant[]; onInventoryChanged: () => void; onInventory: () => void; sample?: {order: Order; result: PipelineResult}; example: boolean; onLive?: () => void }

export function Plan({inventory, onInventoryChanged, onInventory, sample, example, onLive}: Props) {
  const [inputMode, setInputMode] = useState<'prompt' | 'parts'>('prompt');
  const [prompt, setPrompt] = useState('');
  const [order, setOrder] = useState<Order | null>(null), [result, setResult] = useState<PipelineResult | null>(null);
  const [settings, setSettings] = useState(initialSettings);
  const [uploads, setUploads] = useState<(Upload & {quantity:number})[]>([]), [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(''), [trace, setTrace] = useState<Record<string,unknown> | null>(null);
  const [sheetId, setSheetId] = useState(''), [selectedPart, setSelectedPart] = useState(''), [toolpath, setToolpath] = useState(false);
  const [details, setDetails] = useState(false), [commitDialog, setCommitDialog] = useState(false), [committed, setCommitted] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  // Example and live states stay separate. Switching modes never seeds inventory or starts inference.
  const shownResult = example ? sample?.result ?? null : result;
  const shownOrder = example ? sample?.order ?? null : order;
  const invalidate = () => {setResult(null); setCommitted(false); setError(''); setSelectedPart(''); setToolpath(false);};
  const editOrder = (next: Order) => {invalidate(); setOrder(next);};
  const createOrder = () => {setOrder({order_id:`JOB_${Date.now().toString(36).toUpperCase()}`,material:'',thickness_mm:3,kerf_mm:1,parts:[]}); setInputMode('parts'); invalidate();};
  const parse = async () => {
    if (busy || !prompt.trim()) return;
    setBusy('Interpreting your manufacturing request'); setError(''); setOrder(null); invalidate();
    try {const parsed = await api.parse(prompt,uploads.map(u => u.dxf_path)); setOrder(parsed.order); setTrace(parsed.llm_trace);}
    catch(e) {setError((e as Error).message);} finally {setBusy('');}
  };
  const uploadFiles = async (files: File[]) => {
    if (busy) return;
    setBusy(`Importing ${files.length} DXF file${files.length === 1 ? '' : 's'}`); setUploadErrors([]); setError(''); setOrder(null); invalidate();
    const additions: (Upload & {quantity:number})[] = [], failures: string[] = [];
    // Two uploads in flight keeps 100+ definitions usable without flooding the API.
    for (let i=0; i<files.length; i+=2) {
      const responses = await Promise.allSettled(files.slice(i,i+2).map(file => api.upload(file)));
      responses.forEach((response,j) => {if (response.status === 'fulfilled') additions.push({...response.value,quantity:1}); else failures.push(`${files[i+j].name}: ${response.reason instanceof Error ? response.reason.message : String(response.reason)}`);});
    }
    setUploads(old => [...old,...additions]); setUploadErrors(failures); setBusy('');
  };
  const fromUploads = () => {
    editOrder({order_id:`DXF_${Date.now().toString(36).toUpperCase()}`,material:order?.material ?? '',thickness_mm:order?.thickness_mm ?? 3,kerf_mm:order?.kerf_mm ?? 1,
      parts:uploads.map((u,i) => ({part_id:`DXF_${i+1}`,shape_type:'dxf_file',quantity:u.quantity,dxf_path:u.dxf_path}))});
    setInputMode('parts');
  };
  const run = async (commit = false) => {
    if (!order || busy || example) return;
    setError(''); setBusy(commit ? 'Replanning, verifying and updating predicted stock' : 'Nesting and verifying your cutting plan');
    setResult(null); setCommitted(false); setCommitDialog(false);
    try {const planned = await api.execute(order,settings,commit); setResult(planned); setSheetId(planned.nesting.sheet_outcomes.find(s => s.placed_parts.length)?.sheet_id ?? ''); setSelectedPart(''); setCommitted(commit); if(commit) onInventoryChanged();}
    catch(e) {setError((e as Error).message);} finally {setBusy('');}
  };
  const outcomes = shownResult?.nesting.sheet_outcomes.filter(s => s.placed_parts.length > 0) ?? [];
  const outcome = outcomes.find(s => s.sheet_id === sheetId) ?? outcomes[0];
  const stock = shownResult?.candidate_sheets.find(s => s.sheet_id === outcome?.sheet_id);
  const program = shownResult?.gcode_programs.find(p => p.sheet_id === outcome?.sheet_id);
  const complete = shownResult ? batchIsComplete(shownResult) : false;
  const compatible = shownOrder ? inventory.filter(s => s.material === shownOrder.material && Math.abs(s.thickness_mm-shownOrder.thickness_mm) <= .01 && (settings.allow_demo_stock || !['demo','local_threshold'].includes(s.inventory_source) && !s.sheet_id.startsWith('DEMO_'))) : [];
  useEffect(() => {setSelectedPart(''); setToolpath(false);}, [example]);
  return <>
    <div className="workspace-grid plan-grid"><section className="panel input-panel">
      <div className="panel-heading"><span className="step-number">01</span><div><h2>{example ? 'A second life for this sheet.' : 'Your next job'}</h2><p>{example ? 'A captured, verified example to explore.' : 'Describe it. Review it. Make room for it.'}</p></div></div>
      {example && sample ? <><div className="example-note"><span className="badge neutral">Recorded example</span><p>A synthetic L-cutout sheet, planned by the actual backend. No cloud request runs during this replay.</p></div><OrderEditor order={sample.order} onChange={() => {}} disabled /><button className="button primary full" onClick={onLive}>Plan your own job <ArrowUpRight size={15} /></button></> : <>
        <div className="segmented-control"><button className={inputMode === 'prompt' ? 'active' : ''} disabled={!!busy} onClick={() => setInputMode('prompt')}>Describe a job</button><button className={inputMode === 'parts' ? 'active' : ''} disabled={!!busy} onClick={() => {setInputMode('parts'); if(!order) createOrder();}}>Build parts list</button></div>
        {inputMode === 'prompt' && <><label className="field-label" htmlFor="manufacturing-prompt">Manufacturing request</label><textarea id="manufacturing-prompt" disabled={!!busy} value={prompt} onChange={e => {setPrompt(e.target.value); setOrder(null); setTrace(null); invalidate();}} placeholder="Cut 8 plates, 50 × 30 mm, and 4 discs, diameter 20 mm, from 3 mm steel. Kerf 1 mm." /><p className="hint">Include quantity, dimensions, thickness and exact material grade.</p><button className="button primary full" disabled={!!busy || !prompt.trim()} onClick={() => void parse()}>Review order <ChevronRight size={15} /></button></>}
        <div className="divider" /><div className="upload-heading"><span className="eyebrow">VENDOR PARTS</span><span className="muted">{uploads.length ? `${uploads.length} definitions` : '.DXF · mm'}</span></div>
        <input className="sr-only" type="file" ref={uploadInput} aria-label="Vendor DXF files" accept=".dxf" multiple disabled={!!busy} onChange={e => {void uploadFiles(Array.from(e.target.files ?? [])); e.target.value='';}} />
        <button className="dxf-drop" disabled={!!busy} onClick={() => uploadInput.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault(); void uploadFiles(Array.from(e.dataTransfer.files));}}><FilePlus2 size={18} /><span>Add vendor DXFs<small>Choose or drop multiple files</small></span><Plus size={15} /></button>
        <div className="upload-tray">{uploads.map((u,i) => <div className="uploaded-part" key={u.dxf_path}><svg viewBox={`${u.geometry.bounds[0]-2} ${-u.geometry.bounds[3]-2} ${u.geometry.bounds[2]-u.geometry.bounds[0]+4} ${u.geometry.bounds[3]-u.geometry.bounds[1]+4}`} aria-label={`Geometry of ${u.filename}`}><path d={geometryPath(u.geometry)} fill="#b7caa4" fillRule="evenodd" /></svg><div><strong title={u.filename}>{u.filename}</strong><small>{u.hole_count} holes · {formatNumber(u.geometry.area_mm2/100)} cm²</small></div><input aria-label={`Quantity for ${u.filename} ${i+1}`} type="number" min="1" max="10000" disabled={!!busy} value={u.quantity || ''} onChange={e => {setUploads(old => old.map((v,j) => i === j ? {...v,quantity:Number(e.target.value)} : v)); setOrder(null); invalidate();}} /><button className="icon-button" aria-label={`Remove upload ${u.filename} ${i+1}`} disabled={!!busy} onClick={() => {setUploads(old => old.filter((_,j) => j !== i)); setOrder(null); invalidate();}}><Trash2 size={12} /></button></div>)}</div>
        {!!uploads.length && <button className="button secondary full" disabled={!!busy || uploads.some(u => !Number.isInteger(u.quantity) || u.quantity < 1 || u.quantity > 10000)} onClick={fromUploads}>Use {uploads.reduce((n,u) => n+u.quantity,0)} uploaded parts <ChevronRight size={14} /></button>}
        <details className="contract-note"><summary>What DXF files can I use?</summary><p>One outer boundary with optional disjoint holes. Closed, straight LWPOLYLINE contours in millimetres, up to 5 MB per file. Flatten curves to polylines before uploading. Native circles, arcs, splines, blocks and open contours are rejected.</p></details>
        {!!uploadErrors.length && <details open className="upload-failures"><summary>{uploadErrors.length} file{uploadErrors.length === 1 ? '' : 's'} could not be imported</summary>{uploadErrors.map((e,i) => <p key={i}>{e}</p>)}</details>}
        {order && <form onSubmit={e => {e.preventDefault(); void run();}}><div className="divider" /><OrderEditor order={order} onChange={editOrder} disabled={!!busy} />
          <details className="process-details"><summary><SettingsIcon />Controller & process settings</summary><fieldset disabled={!!busy}><Field label="Controller profile"><select value={settings.machine_profile} onChange={e => {setSettings({...settings,machine_profile:e.target.value as ProcessSettings['machine_profile']}); invalidate();}}><option value="ISO_6983_GRBL">GRBL · ISO 6983</option><option value="LINUXCNC_LASER">LinuxCNC · laser</option></select></Field><div className="field-grid">{(['cut_feedrate_mm_min','laser_power_s','pierce_delay_sec','lead_in_radius_mm'] as const).map(key => <Field key={key} label={{cut_feedrate_mm_min:'Feed (mm/min)',laser_power_s:'Power (S)',pierce_delay_sec:'Pierce delay (s)',lead_in_radius_mm:'Lead-in radius (mm)'}[key]}><input required type="number" min={key==='cut_feedrate_mm_min'||key==='laser_power_s'?1:0} max={{cut_feedrate_mm_min:100000,laser_power_s:1000,pierce_delay_sec:60,lead_in_radius_mm:10}[key]} step={key==='laser_power_s'?1:.1} value={settings[key]} onChange={e => {setSettings({...settings,[key]:Number(e.target.value)}); invalidate();}} /></Field>)}</div><p className="hint">Defaults are demonstration settings. Qualify feed, power and work origin for your equipment. Output follows centerline contours.</p></fieldset></details>
          <label className="checkbox-label"><input type="checkbox" disabled={!!busy} checked={settings.allow_demo_stock} onChange={e => {setSettings({...settings,allow_demo_stock:e.target.checked}); invalidate();}} />Include demo / local-threshold stock</label>
          <div className="stock-availability"><Layers2 size={14} /><span>{compatible.length} compatible sheets in current inventory</span><button type="button" className="text-button" onClick={onInventory}>View →</button></div>
          <button className="button primary full" type="submit" disabled={!!busy || !order.parts.length}>Nest & verify <ChevronRight size={15} /></button>
        </form>}
        {trace && <details className="contract-note"><summary>Order interpretation details</summary><pre>{JSON.stringify(trace,null,2)}</pre></details>}
      </>}
      {busy && <Busy label={busy} />}<ErrorNotice message={error} />
    </section>
    <div className="result-column"><section className="panel canvas-panel"><div className="canvas-heading"><div><span className="eyebrow">{shownResult ? 'CUTTING PLAN' : 'SPATIAL WORKSPACE'}</span><h2>{shownResult ? complete ? 'A useful future for this remnant.' : 'Some parts still need a home.' : 'Room for your next idea.'}</h2></div><span className={`badge ${shownResult ? complete ? 'good' : 'warn' : 'neutral'}`}>{shownResult ? complete ? <><ShieldCheck size={12} />Software verified</> : 'Partial batch' : 'Plan view'}</span></div>
      {!!outcomes.length && <div className="sheet-tabs" role="tablist" aria-label="Sheets in cutting plan">{outcomes.map((s,i) => <button key={s.sheet_id} role="tab" aria-selected={outcome?.sheet_id===s.sheet_id} onClick={() => {setSheetId(s.sheet_id); setSelectedPart('');}}><Layers2 size={12} />Sheet {i+1}<span>{s.placed_parts.length} parts</span></button>)}</div>}
      <SheetViewer key={`${example}-${outcome?.sheet_id ?? 'empty'}`} geometry={stock?.geometry} parts={outcome?.placed_parts} program={program} zone={outcome?.kerf_safe_zone} title="Nesting layout" selected={selectedPart} onSelect={setSelectedPart} toolpath={toolpath} />
      {shownResult ? <><div className="metric-strip"><div><strong>{shownResult.nesting.total_placed}<small> / {shownResult.nesting.total_requested}</small></strong><span>parts placed</span></div><div><strong>{formatNumber(shownResult.metrics.usable_area_utilization_pct)}<small>%</small></strong><span>usable area occupied</span></div><div><strong>{shownResult.metrics.sheets_used}</strong><span>sheet{shownResult.metrics.sheets_used===1?'':'s'} used</span></div></div>
        <div className="action-row"><button className="button secondary" disabled={!program?.verification.verified_safe} onClick={() => {if(program?.verification.verified_safe) downloadText(program.gcode_text,`${example?'example-':''}${program.sheet_id}.nc`);}}><ArrowDownToLine size={14} />{example?'Example G-code':'Download G-code'}</button><button className={toolpath?'button secondary':'button ghost'} aria-pressed={toolpath} disabled={!program} onClick={() => setToolpath(v => !v)}><Play size={13} />{toolpath?'Hide planned path':'Inspect planned path'}</button><button className="button ghost" onClick={() => setDetails(v=>!v)}><FileText size={13} />{details?'Hide details':'Verification'}</button></div>
        <div className="canvas-caption"><span className="pulse-square" />{example?'Recorded backend output · synthetic station · no live inference':committed?'Predicted stock updated. This is the newly planned and verified result.':'Preview only · stock has not changed.'}</div>
      </> : <div className="canvas-caption"><span className="pulse-square" />Describe a job or build a parts list. Review it before nesting.</div>}
    </section>
    {shownResult && <>
      {!complete && <div className="notice warning"><FileText size={17} /><div><strong>{shownResult.nesting.total_requested-shownResult.nesting.total_placed} parts were not placed.</strong><p>{shownResult.nesting.unplaced_instances.join(', ')}</p><p>Programs cover the placed subset only. A partial batch cannot update inventory.</p></div></div>}
      {details && <section className="panel verification-panel"><h3><ShieldCheck size={17} />Verification details</h3><div className="check-row"><span>Placement geometry</span><span>{shownResult.nesting.sanitizer_verified ? <><Check size={13} />Passed</> : 'Failed'}</span></div>{shownResult.gcode_programs.map(p => <div key={p.sheet_id} className="program-check"><strong>{p.sheet_id}</strong><div className="check-row"><span>Final G-code program</span><span>{p.verification.verified_safe?'Passed':'Failed'}</span></div><div className="check-row"><span>Inside-out cut order</span><span>{p.verification.inside_out_order_valid?'Passed':'Failed'}</span></div><div className="check-row"><span>Path across stock holes / outside sheet</span><span>{p.verification.hole_collision_length_mm} / {p.verification.outside_sheet_length_mm} mm</span></div></div>)}<p>{shownResult.verification_scope}</p><div className="timing-grid">{Object.entries(shownResult.timings_ms).map(([key,value])=><div key={key}><span>{key.replace(/_ms$/,'').replaceAll('_',' ')}</span><strong>{formatNumber(value/1000,2)}s</strong></div>)}</div><button className="button secondary" onClick={() => downloadText(JSON.stringify(shownResult,null,2),`${example?'example-':''}cutting-plan.json`,'application/json')}>Download result JSON <ArrowDownToLine size={13} /></button></section>}
      {!example && complete && <section className="panel stock-update"><div><span className="eyebrow">PREDICTED INVENTORY</span><h3>{committed ? 'Stock updated, all sheets together.' : 'Ready to update your stock?'}</h3><p>{committed ? 'Reindex physical remnants after moving them. No cut has been performed by this application.' : 'This action reruns planning, verifies the new result and updates predicted remaining stock atomically.'}</p></div><button className="button secondary" disabled={committed || !!busy} onClick={()=>setCommitDialog(true)}>{committed?<><CheckCircle2 size={14} />Updated</>:<>Replan & update stock <ArrowUpRight size={14} /></>}</button></section>}
    </>}
    </div></div>
    {commitDialog && <Modal title="Update predicted remaining stock?" onClose={()=>setCommitDialog(false)}><p>The backend will plan this order again against current stock. The returned layout may differ from this preview. Every resulting program must verify before any sheet changes.</p><p>This records a predicted cut. It does not send instructions to a machine or confirm fabrication. Inspect the returned result before using its output.</p><div className="modal-actions"><button className="button secondary" onClick={()=>setCommitDialog(false)}>Keep preview</button><button className="button primary" onClick={()=>void run(true)}>Replan & update stock</button></div></Modal>}
  </>;
}
function SettingsIcon() {return <Settings2 size={13} />;}
