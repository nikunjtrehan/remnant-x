import { useEffect, useState } from 'react';
import { ArrowUpRight, Boxes, Camera, ChevronRight, CircleHelp, LayoutGrid, Play, ScanLine, Settings2 } from 'lucide-react';
import { Plan } from './Plan';
import { Capture } from './Capture';
import { Inventory } from './Inventory';
import { api } from './api';
import { Modal } from './ui';
import type { Remnant } from './types';

export default function App() {
  const [tab, setTab] = useState('Plan a job');
  const [inventory, setInventory] = useState<Remnant[]>([]), [loading, setLoading] = useState(false);
  const [inventoryError, setInventoryError] = useState(''), [connected, setConnected] = useState(false), [guide, setGuide] = useState(false);
  const refresh = async () => {
    setLoading(true); setInventoryError('');
    try {const data = await api.inventory(); setInventory(data.remnants); setConnected(true);}
    catch(e) {setInventoryError((e as Error).message); setConnected(false);} finally {setLoading(false);}
  };
  useEffect(() => {void api.health().then(() => setConnected(true)).catch(() => setConnected(false)); void refresh();}, []);
  return <div className="app-shell">
    <aside className="rail"><a className="brand" href="/" aria-label="Remnant X home"><span className="brand-mark"><span /></span><span>remnant<span className="brand-x">x</span><small>THE MATERIAL WORKBENCH</small></span></a>
      <span className="rail-caption">WORKSPACE</span><nav>{[{ label: 'Plan a job', icon: LayoutGrid }, { label: 'Scan a remnant', icon: ScanLine }, { label: 'Inventory', icon: Boxes }].map(item => <button key={item.label} className={tab === item.label ? 'rail-link selected' : 'rail-link'} onClick={() => setTab(item.label)} aria-current={tab === item.label ? 'page' : undefined}><item.icon size={18} />{item.label}{tab === item.label && <ChevronRight size={15} />}</button>)}</nav>
      <div className="rail-note"><span className="rail-note-icon"><Camera size={19} /></span><strong>Waste is a design problem.</strong><p>Make something useful from what’s already there.</p></div>
      <div className="rail-bottom"><button className="rail-link" onClick={() => setGuide(true)}><CircleHelp size={17} />Workbench guide<ArrowUpRight size={14} /></button><div className="avatar-row"><span className="avatar">RX</span><div>Local workshop<small>Desktop workspace</small></div><Settings2 size={16} /></div></div>
    </aside>
    <main className="main"><header className="topbar"><div className="breadcrumb">Workspace <ChevronRight size={13} /><span>{tab}</span></div><button className={`connection connection-button ${connected ? '' : 'offline'}`} onClick={() => void refresh()}><i />{connected ? 'Backend connected' : 'Backend offline · retry'}</button></header>
      <div className="page-heading"><div><p className="eyebrow">LESS SCRAP. MORE POSSIBILITY.</p><h1>{tab === 'Plan a job' ? <>The sheet you have.<br /><span>The parts you need.</span></> : tab === 'Scan a remnant' ? <>Start with what’s left.<br /><span>See what’s possible.</span></> : <>Useful material.<br /><span>Already in your workshop.</span></>}</h1><p>{tab === 'Plan a job' ? 'From a remnant to a verified cutting plan, in one workspace.' : tab === 'Scan a remnant' ? 'A station photograph becomes geometry. The holes come with it.' : 'Inspect your sheets, their cutouts and the space you can still use.'}</p></div><button className="button secondary" onClick={() => setGuide(true)}><Play size={15} />Workbench guide<ArrowUpRight size={15} /></button></div>
      <div hidden={tab !== 'Plan a job'}><Plan inventory={inventory} onInventoryChanged={() => void refresh()} onInventory={() => setTab('Inventory')} example={false} /></div>
      <div hidden={tab !== 'Scan a remnant'}><Capture onSaved={() => void refresh()} /></div>
      <div hidden={tab !== 'Inventory'}><Inventory remnants={inventory} loading={loading} error={inventoryError} onRefresh={() => void refresh()} onScan={() => setTab('Scan a remnant')} example={false} /></div>
      <footer className="page-footer"><span>Built for the material that’s already here.</span><span>Perception → geometry → verified output</span></footer>
    </main>
    {guide && <Modal title="One sheet. A second possibility." onClose={() => setGuide(false)}><ol className="guide-list"><li><strong>Set up the station.</strong><p>Save the spans between the outer black-square edges and the printed black marker size. IDs 0–3 stay at their assigned corners.</p></li><li><strong>Scan the remnant.</strong><p>Choose a photo. Marker and calibration checks run before SAM. Supply the material grade and thickness; SAM extracts the outline and holes.</p></li><li><strong>Plan and inspect.</strong><p>Review a structured parts list, nest it against compatible stock and inspect the verified program. The system predicts stock changes; no machine is connected.</p></li></ol><button className="button primary full" onClick={() => {setGuide(false); setTab('Scan a remnant');}}>Open scanner <ChevronRight size={15} /></button></Modal>}
  </div>;
}
