import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SheetViewer } from './SheetViewer';
import { geometryPath, pointsPath } from './geometry';
const geometry = { exterior: [[10, 20], [110, 20], [110, 70], [10, 70]] as [number, number][], holes: [[[30, 30], [40, 30], [40, 40], [30, 40]]] as [number, number][][], bounds: [10, 20, 110, 70] as [number, number, number, number], area_mm2: 4900 };
describe('millimetre workspace', () => {
  it('flips Y once and preserves hole rings in already positioned geometry', () => {
    expect(pointsPath([[10, 20], [30, 40]])).toBe('M10,-20 L30,-40 Z');
    expect(geometryPath(geometry)).toContain('M30,-30');
    render(<SheetViewer geometry={geometry} />);
    expect(screen.getByText('100 mm')).toBeTruthy();
    expect(screen.getByText('50 mm')).toBeTruthy();
  });
  it('supports keyboard part selection and bounded zoom/reset', () => {
    let selected = '';
    render(<SheetViewer geometry={geometry} parts={[{instance_id:'PART_1',part_id:'PART',name:'Part',rotation_deg:90,geometry}]} onSelect={id => {selected = id;}} />);
    fireEvent.keyDown(screen.getByRole('button', {name: 'Select PART_1'}), {key: 'Enter'});
    expect(selected).toBe('PART_1');
    fireEvent.click(screen.getByRole('button', {name: 'Zoom in'}));
    expect(screen.getByText('125%')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'Fit sheet'}));
    expect(screen.getByText('100%')).toBeTruthy();
  });
});
