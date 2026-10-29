import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Plan, batchIsComplete } from './Plan';
import { api } from './api';
import type { Geometry, Order, PipelineResult } from './types';
vi.mock('./api', () => ({api:{parse:vi.fn(),execute:vi.fn(),upload:vi.fn()},downloadText:vi.fn()}));
const geometry: Geometry = {exterior:[[0,0],[100,0],[100,100],[0,100]],holes:[],bounds:[0,0,100,100],area_mm2:10000};
const order: Order = {order_id:'TEST',material:'ss304',thickness_mm:3,kerf_mm:1,parts:[{part_id:'DISC',shape_type:'circle',diameter_mm:20,quantity:2}]};
const result: PipelineResult = {
  status:'BATCH_COMPLETED',machine_profile:'ISO_6983_GRBL',timings_ms:{total_ms:100},verification_scope:'Software geometry only.',order:{...order,total_parts_count:2},
  metrics:{sheets_used:1,usable_area_utilization_pct:6.2,placed_solid_area_mm2:620,input_usable_area_mm2:10000},
  candidate_sheets:[{sheet_id:'S1',material:'ss304',thickness_mm:3,inventory_source:'sam',geometry,outer_area_mm2:10000,usable_area_mm2:10000,hole_count:0,dxf_path:''}],
  nesting:{total_requested:2,total_placed:2,sanitizer_verified:true,unplaced_instances:[],search:{},sheet_outcomes:[{sheet_id:'S1',initial_usable_area_mm2:10000,remaining_usable_area_mm2:9380,utilization_pct:6.2,kerf_safe_zone:null,placed_parts:[{instance_id:'DISC_1',part_id:'DISC',name:'disc',geometry,rotation_deg:0}]}]},
  gcode_programs:[{sheet_id:'S1',origin_x_mm:0,origin_y_mm:0,gcode_text:'G21\nM30',ordered_loops:[],verification:{verified_safe:true,inside_out_order_valid:true,hole_collision_length_mm:0,outside_sheet_length_mm:0,total_cut_distance_mm:40,error_message:''}}],committed_remnants:[],
};
const props = {inventory:[],onInventoryChanged:vi.fn(),onInventory:vi.fn(),example:false};
beforeEach(() => vi.resetAllMocks());
async function parseOrder() {
  vi.mocked(api.parse).mockResolvedValue({order:structuredClone(order),llm_trace:{provider:'baseten'}});
  await userEvent.type(screen.getByLabelText('Manufacturing request'),'Make 2 discs diameter 20mm in 3mm ss304, kerf 1mm');
  await userEvent.click(screen.getByRole('button',{name:'Review order'}));
  await screen.findByLabelText('Quantity · DISC');
}
describe('order workflow', () => {
  it('requires order review, preserves exact grades and invalidates output on editing', async () => {
    vi.mocked(api.execute).mockResolvedValue(result);
    render(<Plan {...props} />); await parseOrder();
    expect((screen.getByLabelText('Material / exact grade') as HTMLInputElement).value).toBe('ss304');
    await userEvent.click(screen.getByRole('button',{name:'Nest & verify'}));
    await screen.findByText('Software verified');
    expect(api.execute).toHaveBeenCalledWith(expect.objectContaining({material:'ss304'}),expect.anything(),false);
    await userEvent.clear(screen.getByLabelText('Quantity · DISC'));
    expect(screen.queryByRole('button',{name:'Download G-code'})).toBeNull();
    expect(screen.queryByText('Software verified')).toBeNull();
  });
  it('shows partial placement and never offers a stock update for it', async () => {
    vi.mocked(api.execute).mockResolvedValue({...result,nesting:{...result.nesting,total_placed:1,unplaced_instances:['DISC_2']}});
    render(<Plan {...props} />); await parseOrder();
    await userEvent.click(screen.getByRole('button',{name:'Nest & verify'}));
    await screen.findByText('Partial batch');
    expect(screen.queryByRole('button',{name:/Replan & update stock/})).toBeNull();
    expect(screen.getByText(/Programs cover the placed subset only/)).toBeTruthy();
  });
  it('keeps a live interpretation error visible instead of substituting an example', async () => {
    vi.mocked(api.parse).mockRejectedValue(new Error('ERR_MISSING_INPUT: Supply thickness'));
    render(<Plan {...props} />);
    await userEvent.type(screen.getByLabelText('Manufacturing request'),'Make two discs');
    await userEvent.click(screen.getByRole('button',{name:'Review order'}));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('Supply thickness'));
    expect(screen.queryByText('Software verified')).toBeNull();
  });
  it('binds all successful uploads directly and retains per-file failures', async () => {
    vi.mocked(api.upload).mockResolvedValueOnce({filename:'bracket.dxf',dxf_path:'managed/bracket.dxf',geometry,hole_count:0}).mockRejectedValueOnce(new Error('Unsupported ARC'));
    render(<Plan {...props} />);
    await userEvent.upload(screen.getByLabelText('Vendor DXF files'),[new File(['dxf'],'bracket.dxf',{type:'application/dxf'}),new File(['arc'],'arc.dxf',{type:'application/dxf'})]);
    await screen.findByText('1 file could not be imported');
    const quantity = screen.getByLabelText('Quantity for bracket.dxf 1');
    await userEvent.clear(quantity); await userEvent.type(quantity,'50');
    await userEvent.click(screen.getByRole('button',{name:'Use 50 uploaded parts'}));
    await waitFor(() => expect((screen.getByLabelText('Quantity · DXF_1') as HTMLInputElement).value).toBe('50'));
    expect(api.parse).not.toHaveBeenCalled();
  });
});
describe('whole-batch completion', () => {
  it('rejects absent, wrong-sheet and unsafe program verification even with equal placement counts', () => {
    expect(batchIsComplete(result)).toBe(true);
    expect(batchIsComplete({...result,gcode_programs:[]})).toBe(false);
    expect(batchIsComplete({...result,gcode_programs:[{...result.gcode_programs[0],sheet_id:'OTHER'}]})).toBe(false);
    expect(batchIsComplete({...result,gcode_programs:[{...result.gcode_programs[0],verification:{...result.gcode_programs[0].verification,verified_safe:false}}]})).toBe(false);
  });
});
