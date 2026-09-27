import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { EvaluationResponse, PersistedSegmentationResponse } from '../../api/api.models';
import { SegmentationCanvasComponent } from './segmentation-canvas/segmentation-canvas.component';
import { SegmentationWorkspaceComponent } from './segmentation-workspace.component';

describe('Persisted segmentation workspace', () => {
  let fixture: ComponentFixture<SegmentationWorkspaceComponent>;
  let component: SegmentationWorkspaceComponent;
  let http: HttpTestingController;
  let element: HTMLElement;
  const evaluation: EvaluationResponse = {
    evaluation_id: 'evaluation-1', image_id: 'persisted-image', pci_region_id: 6, annotator_code: 'MED01',
    status: 'draft', clinical_ls: null, annotator_confidence: null, created_at: '', finalized_at: null,
  };
  const box = { xMin: 200, yMin: 160, xMax: 800, yMax: 600 };
  const attempt: PersistedSegmentationResponse = {
    attempt_id: 'attempt-1', evaluation_id: 'evaluation-1', sequence_number: 1,
    region: { region_id: 6, region_name: 'Pelvis' }, metadata: { selected_score: 0.987654 },
    mask: { encoding: 'png_base64', media_type: 'image/png', width: 1920, height: 1080, data: 'mask' },
  };

  beforeEach(() => {
    vi.stubGlobal('URL', class extends URL {
      static override createObjectURL = vi.fn().mockReturnValue('blob:persisted');
      static override revokeObjectURL = vi.fn();
    });
    TestBed.configureTestingModule({ imports: [SegmentationWorkspaceComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SegmentationWorkspaceComponent);
    component = fixture.componentInstance;
    element = fixture.nativeElement as HTMLElement;
    fixture.componentRef.setInput('evaluationId', 'evaluation-1');
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    http.verify();
    vi.unstubAllGlobals();
  });

  async function flushEvaluation(response = evaluation): Promise<void> {
    http.expectOne('/api/v1/evaluations/evaluation-1').flush(response);
    await Promise.resolve();
    fixture.detectChanges();
  }

  async function flushImage(): Promise<void> {
    const blob = new Blob(['persisted bytes'], { type: 'image/png' });
    http.expectOne('/api/v1/images/persisted-image/content').flush(blob);
    await Promise.resolve();
    fixture.detectChanges();
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    const image = element.querySelector<HTMLImageElement>('.original')!;
    Object.defineProperties(image, { naturalWidth: { value: 1920 }, naturalHeight: { value: 1080 } });
    image.dispatchEvent(new Event('load'));
    fixture.detectChanges();
  }

  async function ready(): Promise<void> { await flushEvaluation(); await flushImage(); }
  function canvas(): SegmentationCanvasComponent { return fixture.debugElement.query(By.directive(SegmentationCanvasComponent)).componentInstance as SegmentationCanvasComponent; }
  function fail(url: string): void {
    http.expectOne(url).flush({ error: { code: 'unavailable', message: 'Model unavailable. Try again.' } }, { status: 503, statusText: 'Unavailable' });
  }
  async function submit(response = attempt): Promise<void> {
    const pending = component.segment();
    http.expectOne('/api/v1/evaluations/evaluation-1/segmentations').flush(response);
    await pending;
    fixture.detectChanges();
  }

  it('reconstructs from only an evaluation ID, loads in order and releases the persisted URL', async () => {
    expect(element.textContent).toContain('Loading persisted evaluation');
    http.expectNone('/api/v1/images/persisted-image/content');
    await flushEvaluation();
    expect(element.textContent).toContain('Loading persisted image');
    await flushImage();
    expect(element.querySelector('.original')?.getAttribute('src')).toBe('blob:persisted');
    fixture.destroy();
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:persisted');
  });

  it('blocks finalized evaluations before image retrieval or segmentation', async () => {
    await flushEvaluation({ ...evaluation, status: 'finalized' });
    component.prepareBox(box);
    await component.segment();
    expect(element.textContent).toContain('This Evaluation is finalized');
    http.expectNone('/api/v1/images/persisted-image/content');
    http.expectNone('/api/v1/evaluations/evaluation-1/segmentations');
  });

  it('retries failed evaluation retrieval', async () => {
    fail('/api/v1/evaluations/evaluation-1');
    await Promise.resolve();
    fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')).not.toBeNull();
    element.querySelector('button')!.click();
    await ready();
  });

  it('retries only the image after image retrieval fails', async () => {
    await flushEvaluation();
    http.expectOne('/api/v1/images/persisted-image/content').error(new ProgressEvent('error'));
    await Promise.resolve();
    fixture.detectChanges();
    element.querySelector('button')!.click();
    http.expectNone('/api/v1/evaluations/evaluation-1');
    await flushImage();
  });

  it('cleans up a failed image decode and permits image-only retry', async () => {
    await ready();
    element.querySelector('.original')!.dispatchEvent(new Event('error'));
    fixture.detectChanges();
    expect(element.textContent).toContain('could not be displayed');
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:persisted');
    element.querySelector('button')!.click();
    await flushImage();
  });

  it('requires a box and prevents duplicate submissions during inference', async () => {
    await ready();
    await component.segment();
    http.expectNone('/api/v1/evaluations/evaluation-1/segmentations');
    expect(element.querySelector<HTMLButtonElement>('.primary-button')!.disabled).toBe(true);
    canvas().boxChange.emit(box);
    fixture.detectChanges();
    expect(element.querySelector<HTMLButtonElement>('.primary-button')!.disabled).toBe(false);
    const pending = component.segment();
    await component.segment();
    fixture.detectChanges();
    expect(element.textContent).toContain('SAM is processing');
    expect(canvas().disabled()).toBe(true);
    expect(element.querySelector<HTMLButtonElement>('.primary-button')!.disabled).toBe(true);
    http.expectOne('/api/v1/evaluations/evaluation-1/segmentations').flush(attempt);
    await pending;
  });

  it('shows only the latest saved attempt and hides the old mask when preparing another prompt', async () => {
    await ready();
    canvas().boxChange.emit(box);
    await submit();
    expect(element.textContent).toContain('Attempt #1');
    expect(element.textContent).toContain('Segmentation attempt saved');
    expect(element.querySelector('.mask')?.getAttribute('src')).toBe('data:image/png;base64,mask');
    expect(element.textContent).not.toContain('0.987654');
    expect(element.textContent).not.toContain('clinical confidence');
    canvas().boxChange.emit(null);
    fixture.detectChanges();
    expect(element.querySelector('.mask')).toBeNull();
    expect(element.textContent).not.toContain('Attempt #1');
    canvas().boxChange.emit(box);
    await submit({ ...attempt, sequence_number: 2, mask: { ...attempt.mask, data: 'second' } });
    expect(element.textContent).toContain('Attempt #2');
    expect(element.textContent).not.toContain('Attempt #1');
    expect(element.querySelector('.mask')?.getAttribute('src')).toBe('data:image/png;base64,second');
  });

  it('preserves the prompt after segmentation failure for retry', async () => {
    await ready();
    canvas().boxChange.emit(box);
    const pending = component.segment();
    fail('/api/v1/evaluations/evaluation-1/segmentations');
    await pending;
    fixture.detectChanges();
    expect(element.textContent).toContain('Model unavailable. Try again.');
    expect(component.box()).toEqual(box);
    expect(element.querySelector<HTMLButtonElement>('.primary-button')!.disabled).toBe(false);
    await submit();
  });

  it('does not display a mismatched mask as aligned', async () => {
    await ready();
    canvas().boxChange.emit(box);
    await submit({ ...attempt, mask: { ...attempt.mask, width: 10 } });
    expect(element.textContent).toContain('mask dimensions do not match');
    expect(element.querySelector('.mask')).toBeNull();
  });

  it('cancels evaluation retrieval on destruction', () => {
    const request = http.expectOne('/api/v1/evaluations/evaluation-1');
    fixture.destroy();
    expect(request.cancelled).toBe(true);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('revokes the previous URL when reloading image content', async () => {
    await ready();
    const pending = component.load();
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:persisted');
    await flushImage();
    await pending;
  });
});
