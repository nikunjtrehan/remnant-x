import { useState } from 'react';
import { ArrowUpRight, Boxes, Camera, ChevronRight, CircleHelp, LayoutGrid, Play, ScanLine, Settings2 } from 'lucide-react';
import { SheetViewer } from './SheetViewer';

export default function App() {
  const [tab, setTab] = useState('Plan a job');
  return <div className="app-shell">
    <aside className="rail"><a className="brand" href="/" aria-label="Remnant X home"><span className="brand-mark"><span /></span><span>remnant<span className="brand-x">x</span><small>THE MATERIAL WORKBENCH</small></span></a>
      <span className="rail-caption">WORKSPACE</span><nav>{[{ label: 'Plan a job', icon: LayoutGrid }, { label: 'Scan a remnant', icon: ScanLine }, { label: 'Inventory', icon: Boxes }].map(item => <button key={item.label} className={tab === item.label ? 'rail-link selected' : 'rail-link'} onClick={() => setTab(item.label)}><item.icon size={18} />{item.label}{tab === item.label && <ChevronRight size={15} />}</button>)}</nav>
      <div className="rail-note"><span className="rail-note-icon"><Camera size={19} /></span><strong>Waste is a design problem.</strong><p>Make something useful from what’s already there.</p></div>
      <div className="rail-bottom"><button className="rail-link"><CircleHelp size={17} />Workbench guide<ArrowUpRight size={14} /></button><div className="avatar-row"><span className="avatar">RX</span><div>Local workshop<small>Desktop workspace</small></div><Settings2 size={16} /></div></div>
    </aside>
    <main className="main"><header className="topbar"><div className="breadcrumb">Workspace <ChevronRight size={13} /><span>{tab}</span></div><span className="connection"><i />Local workbench</span></header>
      <div className="page-heading"><div><p className="eyebrow">LESS SCRAP. MORE POSSIBILITY.</p><h1>The sheet you have.<br /><span>The parts you need.</span></h1><p>From a remnant to a verified cutting plan, in one workspace.</p></div><button className="button secondary"><Play size={15} />Explore an example<ArrowUpRight size={15} /></button></div>
      <div className="workspace-grid"><section className="panel input-panel"><div className="panel-heading"><span className="step-number">01</span><div><h2>Your next job</h2><p>Tell us what you need to make.</p></div></div><label className="field-label" htmlFor="prompt">Manufacturing request</label><textarea id="prompt" placeholder="Cut 8 plates, 50 × 30 mm, from 3 mm steel. Kerf 1 mm." /><p className="hint">Dimensions in millimetres. Exact grades stay exact.</p><button className="button primary full">Review order <ChevronRight size={16} /></button><div className="divider" /><span className="eyebrow">A SIMPLE, CHECKED WORKFLOW</span><ol className="workflow-list"><li><span>1</span><div>Describe the parts<small>Natural language or a vendor DXF.</small></div></li><li><span>2</span><div>Use what’s in stock<small>Hole-aware placement across sheets.</small></div></li><li><span>3</span><div>Inspect the cutting plan<small>Verified output, ready to review.</small></div></li></ol></section><section className="panel canvas-panel"><div className="canvas-heading"><div><span className="eyebrow">SPATIAL WORKSPACE</span><h2>Room for your next idea.</h2></div><span className="badge neutral">Plan view</span></div><SheetViewer /><div className="canvas-caption"><span className="pulse-square" />Geometry stays in millimetres. Existing holes stay out of the cut.</div></section></div>
      <footer className="page-footer"><span>Built for the material that’s already here.</span><span>Perception → geometry → verified output</span></footer>
    </main>
  </div>;
}
