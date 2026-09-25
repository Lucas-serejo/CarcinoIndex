import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CaseResponse, EvaluationResponse, ImageResponse } from '../api/api.models';
import { ExperimentWorkflowComponent } from './experiment-workflow.component';

describe('Experiment setup', () => {
  let fixture: ComponentFixture<ExperimentWorkflowComponent>;
  let component: ExperimentWorkflowComponent;
  let http: HttpTestingController;
  let element: HTMLElement;
  const regions = { regions: [{ region_id: 0, code: 'R0', display_name: 'Backend region label' }] };
  const clinicalCase: CaseResponse = { case_id: 'case-1', anonymous_patient_code: 'P01', created_at: '2026-09-25T12:00:00Z' };
  const image: ImageResponse = { image_id: 'image-1', case_id: 'case-1', width: 1920, height: 1080, sha256: 'hash', created_at: clinicalCase.created_at };
  const evaluation: EvaluationResponse = {
    evaluation_id: 'evaluation-1', image_id: 'image-1', pci_region_id: 0, annotator_code: 'MED01',
    status: 'draft', clinical_ls: null, annotator_confidence: null, created_at: clinicalCase.created_at, finalized_at: null,
  };
  const file = new File(['image'], 'identifying-name.png', { type: 'image/png' });

  beforeEach(() => {
    vi.stubGlobal('URL', class extends URL {
      static override createObjectURL = vi.fn().mockReturnValue('blob:preview');
      static override revokeObjectURL = vi.fn();
    });
    TestBed.configureTestingModule({ imports: [ExperimentWorkflowComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ExperimentWorkflowComponent);
    component = fixture.componentInstance;
    element = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    http.verify();
    vi.unstubAllGlobals();
  });

  function loadRegions(): void {
    http.expectOne('/api/v1/pci/regions').flush(regions);
    fixture.detectChanges();
  }

  function selectFile(selected = file): void {
    const input = element.querySelector<HTMLInputElement>('#laparoscopic-image')!;
    Object.defineProperty(input, 'files', { configurable: true, value: { item: () => selected } });
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  }

  function fillForm(): void {
    component.form.patchValue({ patientCode: ' P01 ', annotatorCode: ' MED01 ', regionId: 0 });
    selectFile();
  }

  async function flushCase(): Promise<void> {
    const request = http.expectOne('/api/v1/cases');
    expect(request.request.body).toEqual({ anonymous_patient_code: 'P01' });
    http.expectNone('/api/v1/cases/case-1/images');
    request.flush(clinicalCase);
    await Promise.resolve();
  }

  async function flushImage(): Promise<void> {
    const request = http.expectOne('/api/v1/cases/case-1/images');
    expect((request.request.body as FormData).get('image')).toBe(file);
    http.expectNone('/api/v1/images/image-1/evaluations');
    request.flush(image);
    await Promise.resolve();
  }

  function fail(url: string): void {
    http.expectOne(url).flush({ error: { code: 'unavailable', message: 'Please try again.' } }, { status: 503, statusText: 'Unavailable' });
  }

  it('loads backend PCI labels when opened', () => {
    expect(element.textContent).toContain('Loading PCI regions');
    expect(element.querySelector<HTMLButtonElement>('[type="submit"]')?.disabled).toBe(true);
    loadRegions();
    expect(element.querySelector('select')?.textContent).toContain('Backend region label');
  });

  it('prevents submission with missing fields', async () => {
    loadRegions();
    await component.submit();
    expect(component.form.invalid).toBe(true);
    expect(component.form.controls.file.touched).toBe(true);
    http.expectNone('/api/v1/cases');
  });

  it.each(['   ', 'x'.repeat(129)])('rejects blank or oversized pseudonymous codes', async (code) => {
    loadRegions();
    fillForm();
    component.form.patchValue({ patientCode: code, annotatorCode: code });
    await component.submit();
    expect(component.form.controls.patientCode.invalid).toBe(true);
    expect(component.form.controls.annotatorCode.invalid).toBe(true);
    http.expectNone('/api/v1/cases');
  });

  it('validates trimmed lengths and rejects region values outside the backend list', async () => {
    loadRegions();
    fillForm();
    component.form.patchValue({ patientCode: ` ${'x'.repeat(128)} `, regionId: 12 });
    expect(component.form.controls.patientCode.valid).toBe(true);
    await component.submit();
    http.expectNone('/api/v1/cases');
  });

  it('previews the selected image without rendering its filename', () => {
    loadRegions();
    selectFile();
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);
    expect(element.querySelector('img')?.getAttribute('src')).toBe('blob:preview');
    expect(element.innerHTML).not.toContain(file.name);
    expect(element.querySelector<HTMLInputElement>('[type="file"]')?.value).toBe('');
    selectFile(new File(['next'], 'another.png', { type: 'image/png' }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
    fixture.destroy();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('rejects unsupported image types and releases the old preview', () => {
    loadRegions();
    selectFile();
    selectFile(new File(['text'], 'private.txt', { type: 'text/plain' }));
    expect(component.form.controls.file.value).toBeNull();
    expect(component.previewUrl()).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    expect(element.textContent).toContain('Choose a JPEG or PNG image.');
  });

  it('creates case, image, and evaluation in order and keeps the preview after completion', async () => {
    loadRegions();
    fillForm();
    const pending = component.submit();
    expect(component.stage()).toBe('Creating clinical case');
    await flushCase();
    expect(component.stage()).toBe('Uploading image');
    await flushImage();
    expect(component.stage()).toBe('Creating evaluation');
    const request = http.expectOne('/api/v1/images/image-1/evaluations');
    expect(request.request.body).toEqual({ pci_region_id: 0, annotator_code: 'MED01' });
    request.flush(evaluation);
    await pending;
    fixture.detectChanges();
    expect(element.textContent).toContain('Evaluation ready');
    expect(element.textContent).toContain('Draft');
    expect(element.textContent).toContain('1920 × 1080');
    expect(element.textContent).toContain('Backend region label');
    expect(component.form.disabled).toBe(true);
    expect(component.form.controls.file.value).toBe(file);
    expect(component.previewUrl()).toBe('blob:preview');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    await component.submit();
    http.expectNone('/api/v1/cases');
  });

  it('retries image failure with the existing case and allows replacing only unpersisted inputs', async () => {
    loadRegions();
    fillForm();
    let pending = component.submit();
    await flushCase();
    fail('/api/v1/cases/case-1/images');
    await pending;
    fixture.detectChanges();
    expect(element.textContent).toContain('Uploading image failed');
    expect(element.querySelector<HTMLInputElement>('#patient-code')?.disabled).toBe(true);
    expect(element.querySelector<HTMLInputElement>('[type="file"]')?.disabled).toBe(false);
    expect(component.form.controls.annotatorCode.enabled).toBe(true);
    expect(component.form.controls.regionId.enabled).toBe(true);
    const replacement = new File(['replacement'], 'replacement.jpg', { type: 'image/jpeg' });
    selectFile(replacement);
    pending = component.submit();
    http.expectNone('/api/v1/cases');
    const upload = http.expectOne('/api/v1/cases/case-1/images');
    expect((upload.request.body as FormData).get('image')).toBe(replacement);
    upload.flush(image);
    await Promise.resolve();
    http.expectOne('/api/v1/images/image-1/evaluations').flush(evaluation);
    await pending;
  });

  it('retries evaluation failure without another case or upload and locks the stored image', async () => {
    loadRegions();
    fillForm();
    let pending = component.submit();
    await flushCase();
    await flushImage();
    fail('/api/v1/images/image-1/evaluations');
    await pending;
    fixture.detectChanges();
    expect(element.querySelector<HTMLInputElement>('#patient-code')?.disabled).toBe(true);
    expect(element.querySelector<HTMLInputElement>('[type="file"]')?.disabled).toBe(true);
    expect(component.form.controls.annotatorCode.enabled).toBe(true);
    expect(component.form.controls.regionId.enabled).toBe(true);
    selectFile(new File(['ignored'], 'ignored.png', { type: 'image/png' }));
    expect(component.form.controls.file.value).toBe(file);
    component.form.controls.annotatorCode.setValue(' MED02 ');
    pending = component.submit();
    http.expectNone('/api/v1/cases');
    http.expectNone('/api/v1/cases/case-1/images');
    const request = http.expectOne('/api/v1/images/image-1/evaluations');
    expect(request.request.body).toEqual({ pci_region_id: 0, annotator_code: 'MED02' });
    request.flush({ ...evaluation, annotator_code: 'MED02' });
    await pending;
    expect(component.evaluation()?.annotator_code).toBe('MED02');
  });

  it('prevents duplicate submission during every running stage', async () => {
    loadRegions();
    fillForm();
    const pending = component.submit();
    await component.submit();
    expect(component.form.disabled).toBe(true);
    await flushCase();
    await component.submit();
    await flushImage();
    await component.submit();
    http.expectOne('/api/v1/images/image-1/evaluations').flush(evaluation);
    await pending;
  });

  it('allows all fields to be corrected after case creation fails', async () => {
    loadRegions();
    fillForm();
    const pending = component.submit();
    fail('/api/v1/cases');
    await pending;
    expect(component.form.enabled).toBe(true);
    expect(component.form.controls.patientCode.enabled).toBe(true);
    expect(component.clinicalCase()).toBeNull();
    expect(component.failure()?.stage).toBe('Creating clinical case');
  });

  it('retries region loading and blocks submission until regions are available', async () => {
    fail('/api/v1/pci/regions');
    fixture.detectChanges();
    fillForm();
    await component.submit();
    http.expectNone('/api/v1/cases');
    const retry = Array.from(element.querySelectorAll('button')).find(button => button.textContent?.includes('Retry region'));
    retry?.click();
    loadRegions();
    expect(component.regionState()).toBe('success');
  });

  it('treats an empty region response as retryable', () => {
    http.expectOne('/api/v1/pci/regions').flush({ regions: [] });
    fixture.detectChanges();
    expect(element.textContent).toContain('No PCI regions are available');
    expect(component.regionState()).toBe('error');
  });

  it('cancels pending work on destruction without starting the next stage', async () => {
    loadRegions();
    fillForm();
    const pending = component.submit();
    const request = http.expectOne('/api/v1/cases');
    fixture.destroy();
    await pending;
    expect(request.cancelled).toBe(true);
    http.expectNone('/api/v1/cases/case-1/images');
  });
});
