import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ImageBox } from '../../../api/api.models';
import { SegmentationCanvasComponent } from './segmentation-canvas.component';

describe('Segmentation canvas geometry', () => {
  let fixture: ComponentFixture<SegmentationCanvasComponent>;
  let component: SegmentationCanvasComponent;
  let svg: SVGSVGElement;
  let rect: DOMRect;
  let emitted = vi.fn<(box: ImageBox | null) => void>();

  beforeEach(() => {
    fixture = TestBed.createComponent(SegmentationCanvasComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('imageUrl', 'blob:persisted');
    fixture.detectChanges();
    const image = (fixture.nativeElement as HTMLElement).querySelector('img')!;
    Object.defineProperties(image, { naturalWidth: { value: 1920 }, naturalHeight: { value: 1080 } });
    image.dispatchEvent(new Event('load'));
    svg = (fixture.nativeElement as HTMLElement).querySelector('svg')!;
    rect = { left: 10, top: 20, width: 960, height: 540 } as DOMRect;
    vi.spyOn(svg, 'getBoundingClientRect').mockImplementation(() => rect);
    svg.setPointerCapture = vi.fn();
    svg.hasPointerCapture = vi.fn().mockReturnValue(true);
    svg.releasePointerCapture = vi.fn();
    emitted = vi.fn();
    component.boxChange.subscribe(emitted);
  });

  function pointer(type: string, x: number, y: number, id = 1): void {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.assign(event, { clientX: x + rect.left, clientY: y + rect.top, pointerId: id, isPrimary: true, button: 0 });
    svg.dispatchEvent(event);
    fixture.detectChanges();
  }

  it('captures natural dimensions and emits original pixels at 50% scale', () => {
    expect(component.width()).toBe(1920);
    expect(component.height()).toBe(1080);
    pointer('pointerdown', 100, 80);
    pointer('pointermove', 400, 300);
    pointer('pointerup', 400, 300);
    expect(emitted).toHaveBeenLastCalledWith({ xMin: 200, yMin: 160, xMax: 800, yMax: 600 });
    expect(svg.setPointerCapture).toHaveBeenCalledWith(1);
    expect(svg.releasePointerCapture).toHaveBeenCalledWith(1);
  });

  it('normalizes reverse dragging and clamps to original image boundaries', () => {
    pointer('pointerdown', 1100, 700);
    pointer('pointerup', -100, -80);
    expect(emitted).toHaveBeenLastCalledWith({ xMin: 0, yMin: 0, xMax: 1920, yMax: 1080 });
  });

  it.each([[0, 0], [1, 1], [100, 0], [2, 100]])('rejects a tiny or zero-area drag (%s, %s)', (x, y) => {
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 100 + x, 80 + y);
    expect(component.box()).toBeNull();
    expect(emitted.mock.calls.every(call => call[0] === null)).toBe(true);
  });

  it('clears the prompt', () => {
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 400, 300);
    component.clearBox();
    expect(component.box()).toBeNull();
    expect(emitted).toHaveBeenLastCalledWith(null);
  });

  it('preserves original geometry across resize and maps new prompts using current bounds', () => {
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 400, 300);
    const box = component.box();
    rect = { left: 30, top: 40, width: 480, height: 270 } as DOMRect;
    fixture.detectChanges();
    expect(component.box()).toEqual(box);
    pointer('pointerdown', 50, 40);
    pointer('pointerup', 200, 150);
    expect(emitted).toHaveBeenLastCalledWith(box);
  });

  it('cancels safely, ignores other pointers, and permits the next drag', () => {
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 400, 300, 2);
    pointer('pointercancel', 400, 300);
    pointer('pointermove', 500, 400);
    expect(component.box()).toBeNull();
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 400, 300);
    expect(component.box()?.xMax).toBe(800);
  });

  it('blocks drawing while inference runs', () => {
    fixture.componentRef.setInput('disabled', true);
    pointer('pointerdown', 100, 80);
    pointer('pointerup', 400, 300);
    expect(emitted).not.toHaveBeenCalled();
  });

  it('rejects mismatched mask dimensions and displays a matching overlay', () => {
    const mask = { encoding: 'png_base64', media_type: 'image/png', width: 100, height: 100, data: 'mask' };
    fixture.componentRef.setInput('mask', mask);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('mask dimensions do not match');
    expect((fixture.nativeElement as HTMLElement).querySelector('.mask')).toBeNull();
    fixture.componentRef.setInput('mask', { ...mask, width: 1920, height: 1080 });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.mask')?.getAttribute('src')).toBe('data:image/png;base64,mask');
  });
});
