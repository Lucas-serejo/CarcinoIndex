import { LanguageService } from '../i18n/language.service';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { SegmentationWorkspaceComponent } from './segmentation-workspace/segmentation-workspace.component';
import { CaseResponse, EvaluationResponse, ImageResponse } from '../api/api.models';
import { ExperimentWorkflowComponent } from './experiment-workflow.component';
import { ClinicalAssessmentComponent } from './clinical-assessment/clinical-assessment.component';

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
    reviewed_attempt_id: null, segmentation_quality: null, status: 'draft', clinical_ls: null, annotator_confidence: null, created_at: clinicalCase.created_at, finalized_at: null,
  };
  const file = new File(['image'], 'identifying-name.png', { type: 'image/png' });

  beforeEach(() => {
    vi.stubGlobal('URL', class extends URL {
      static override createObjectURL = vi.fn().mockReturnValue('blob:preview');
      static override revokeObjectURL = vi.fn();
    });
    TestBed.configureTestingModule({ imports: [ExperimentWorkflowComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(LanguageService).select('en');
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

  it('requires a region decision and sends null for the explicit undetermined option across languages', async () => {
    loadRegions(); fillForm();
    component.form.controls.regionId.setValue(null);
    await component.submit();
    http.expectNone('/api/v1/cases');
    const select = element.querySelector<HTMLSelectElement>('#pci-region')!;
    select.selectedIndex = select.options.length - 1;
    select.dispatchEvent(new Event('change'));
    expect(component.form.controls.regionId.value).toBe('undetermined');
    component.i18n.select('pt-BR'); fixture.detectChanges();
    expect(select.selectedOptions[0].textContent).toContain('Não foi possível determinar');
    const pending = component.submit();
    await flushCase(); await flushImage();
    const request = http.expectOne('/api/v1/images/image-1/evaluations');
    expect(request.request.body).toEqual({ pci_region_id: null, annotator_code: 'MED01' });
    request.flush({ ...evaluation, pci_region_id: null }); await pending;
    fixture.detectChanges();
    expect(element.textContent).toContain('Não determinada');
    expect(element.textContent).not.toContain('null');
    component.i18n.select('en'); fixture.detectChanges();
    expect(element.textContent).toContain('Region undetermined');
    expect(component.evaluation()?.pci_region_id).toBeNull();
  });

  it('preserves setup controls, preview and validation when switching language', () => {
    loadRegions();
    expect(element.querySelector('label[for="patient-code"]')?.textContent).toBe('Pseudonymous case code');
    expect(element.querySelector('#privacy-note')?.textContent).toContain('does not establish that different images belong to the same patient');
    fillForm();
    component.form.controls.patientCode.markAsTouched();
    const values = component.form.getRawValue();
    const preview = component.previewUrl();
    const input = element.querySelector('#patient-code');
    component.i18n.select('pt-BR');
    fixture.detectChanges();
    expect(element.textContent).toContain('Preparação do experimento');
    expect(element.querySelector('label[for="patient-code"]')?.textContent).toBe('Código pseudonimizado do caso');
    expect(element.querySelector('#privacy-note')?.textContent).toContain('não estabelece que diferentes imagens pertencem ao mesmo paciente');
    expect(element.querySelector('button[type="submit"]')?.textContent).toContain('Iniciar avaliação');
    expect(component.form.getRawValue()).toEqual(values);
    expect(component.previewUrl()).toBe(preview);
    expect(element.querySelector('#patient-code')).toBe(input);
    expect(component.form.controls.patientCode.touched).toBe(true);
    component.i18n.select('en');
    fixture.detectChanges();
    expect(element.textContent).toContain('Experiment setup');
    expect(component.form.getRawValue()).toEqual(values);
    http.expectNone('/api/v1/cases');
  });

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

  it('enters F3 with only the persisted evaluation ID and releases setup resources', async () => {
    loadRegions();
    fillForm();
    const pending = component.submit();
    await flushCase();
    await flushImage();
    http.expectOne('/api/v1/images/image-1/evaluations').flush(evaluation);
    await pending;
    fixture.detectChanges();
    expect(element.querySelector('[aria-current="step"]')?.textContent).toContain('Setup');
    const button = Array.from(element.querySelectorAll('button')).find(button => button.textContent?.includes('Segmentation workspace'))!;
    expect(button.disabled).toBe(false);
    button.click();
    fixture.detectChanges();
    const workspace = fixture.debugElement.query(By.directive(SegmentationWorkspaceComponent)).componentInstance as SegmentationWorkspaceComponent;
    expect(workspace.evaluationId()).toBe('evaluation-1');
    expect('file' in workspace).toBe(false);
    expect(component.form.controls.file.value).toBeNull();
    expect(component.previewUrl()).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:preview');
    expect(element.querySelector('[aria-current="step"]')?.textContent).toContain('Segmentation');
    expect(element.querySelector('.steps li')?.textContent).toContain('Complete');
    http.expectOne('/api/v1/evaluations/evaluation-1').flush({ ...evaluation, status: 'finalized' });
    await Promise.resolve();
  });

  it('preserves the reviewed attempt through finalization and starts an independent next evaluation', async () => {
    loadRegions();
    fillForm();
    const initialSetup = component.submit();
    await flushCase(); await flushImage();
    http.expectOne('/api/v1/images/image-1/evaluations').flush(evaluation);
    await initialSetup;
    component.evaluation.set(evaluation);
    component.enterSegmentation(); fixture.detectChanges();
    http.expectOne('/api/v1/evaluations/evaluation-1').flush(evaluation);
    await Promise.resolve();
    http.expectOne('/api/v1/images/image-1/content').flush(new Blob(['image'], { type: 'image/png' }));
    await Promise.resolve(); fixture.detectChanges();
    const workspace = fixture.debugElement.query(By.directive(SegmentationWorkspaceComponent)).componentInstance as SegmentationWorkspaceComponent;
    const original = element.querySelector<HTMLImageElement>('.original')!;
    Object.defineProperties(original, { naturalWidth: { value: 1920 }, naturalHeight: { value: 1080 } });
    original.dispatchEvent(new Event('load'));
    workspace.prepareBox({ xMin: 20, yMin: 20, xMax: 100, yMax: 100 });
    const pending = workspace.segment();
    http.expectOne('/api/v1/evaluations/evaluation-1/segmentations').flush({
      attempt_id: 'attempt-2', evaluation_id: 'evaluation-1', sequence_number: 2,
      region: { region_id: 0, region_name: 'Central' }, metadata: {},
      mask: { encoding: 'png_base64', media_type: 'image/png', width: 1920, height: 1080, data: 'mask' },
    });
    await pending; fixture.detectChanges();
    workspace.continueToClinicalAssessment();
    expect(component.phase()).toBe('segmentation');
    const mask = element.querySelector<HTMLImageElement>('.mask')!;
    Object.defineProperties(mask, { naturalWidth: { value: 1920 }, naturalHeight: { value: 1080 } });
    mask.dispatchEvent(new Event('load')); fixture.detectChanges();
    element.querySelectorAll<HTMLInputElement>('input[name="segmentation-quality"]')[2].click();
    workspace.continueToClinicalAssessment(); fixture.detectChanges();
    expect(component.phase()).toBe('clinical');
    expect(fixture.debugElement.query(By.directive(SegmentationWorkspaceComponent))).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
    const clinical = fixture.debugElement.query(By.directive(ClinicalAssessmentComponent)).componentInstance as ClinicalAssessmentComponent;
    expect(clinical.evaluationId()).toBe('evaluation-1');
    expect(clinical.segmentationReview()).toEqual({ reviewed_attempt_id: 'attempt-2', segmentation_quality: 'inadequate' });
    expect('file' in clinical || 'mask' in clinical || 'metadata' in clinical).toBe(false);
    http.expectOne('/api/v1/evaluations/evaluation-1').flush(evaluation); fixture.detectChanges();
    expect(Array.from(element.querySelectorAll('.steps span')).map(span => span.textContent)).toEqual(['Complete', 'Complete', 'Active']);
    expect(element.textContent).not.toContain('New evaluation');
    component.startNewEvaluation();
    expect(component.evaluation()).toBe(evaluation);
    clinical.form.controls.clinicalLs.setValue(2); clinical.reviewAssessment(); clinical.finalize();
    const finalized: EvaluationResponse = {
      ...evaluation, status: 'finalized', clinical_ls: 2, finalized_at: '2026-09-26T12:00:00Z',
      reviewed_attempt_id: 'attempt-2', segmentation_quality: 'inadequate',
    };
    const request = http.expectOne('/api/v1/evaluations/evaluation-1/finalize');
    expect(request.request.body).toEqual({
      clinical_ls: 2, annotator_confidence: null, reviewed_attempt_id: 'attempt-2', segmentation_quality: 'inadequate',
    });
    request.flush(finalized); fixture.detectChanges();
    expect(component.evaluation()).toEqual(finalized);
    expect(element.textContent).toContain('Inadequate');
    expect(Array.from(element.querySelectorAll('.steps span')).map(span => span.textContent)).toEqual(['Complete', 'Complete', 'Complete']);
    expect(element.querySelector('[aria-current="step"]')).toBeNull();
    expect(element.textContent).toContain('New evaluation');
    component.i18n.select('pt-BR'); fixture.detectChanges();
    const nextButton = Array.from(element.querySelectorAll('button')).find(button => button.textContent?.trim() === 'Nova avaliação')!;
    expect(nextButton).toBeDefined();
    const previous = structuredClone(finalized);
    const loadedRegions = component.regions();
    component.imageError.set('Old upload error');
    component.regionError.set('Old region error');
    component.failure.set({ stage: 'Uploading image', message: 'Old failure' });
    component.previewUrl.set('blob:stale-preview');
    nextButton.click(); fixture.detectChanges();
    expect(component.phase()).toBe('setup');
    expect(component.form.getRawValue()).toEqual({ patientCode: '', annotatorCode: 'MED01', regionId: null, file: null });
    expect(Object.values(component.form.controls).every(control => control.enabled && control.pristine && control.untouched)).toBe(true);
    expect(component.form.invalid).toBe(true);
    expect(component.clinicalCase()).toBeNull();
    expect(component.image()).toBeNull();
    expect(component.evaluation()).toBeNull();
    expect(component.segmentationReview()).toBeNull();
    expect(component.previewUrl()).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:stale-preview');
    expect(component.imageError()).toBe('');
    expect(component.regionError()).toBe('');
    expect(component.failure()).toBeNull();
    expect(component.stage()).toBeNull();
    expect(component.i18n.language()).toBe('pt-BR');
    expect(component.regions()).toBe(loadedRegions);
    expect(component.regionState()).toBe('success');
    expect(element.querySelector('select')?.textContent).toContain('Backend region label');
    expect(element.querySelector('app-clinical-assessment')).toBeNull();
    expect(element.textContent).not.toContain('Nova avaliação');
    expect(finalized).toEqual(previous);
    http.expectNone(() => true);

    const newFile = new File(['new image'], 'new.png', { type: 'image/png' });
    component.form.patchValue({ patientCode: 'CASE-002', regionId: 'undetermined' });
    selectFile(newFile);
    const nextSetup = component.submit();
    const newCase = http.expectOne('/api/v1/cases');
    expect(newCase.request.body).toEqual({ anonymous_patient_code: 'CASE-002' });
    newCase.flush({ ...clinicalCase, case_id: 'case-2', anonymous_patient_code: 'CASE-002' });
    await Promise.resolve();
    const newUpload = http.expectOne('/api/v1/cases/case-2/images');
    expect((newUpload.request.body as FormData).get('image')).toBe(newFile);
    newUpload.flush({ ...image, case_id: 'case-2', image_id: 'image-2' });
    await Promise.resolve();
    const newEvaluation = http.expectOne('/api/v1/images/image-2/evaluations');
    expect(newEvaluation.request.body).toEqual({ pci_region_id: null, annotator_code: 'MED01' });
    const second = { ...evaluation, evaluation_id: 'evaluation-2', image_id: 'image-2', pci_region_id: null };
    newEvaluation.flush(second); await nextSetup;
    expect(component.evaluation()).toEqual(second);
    expect(finalized).toEqual(previous);
    component.enterSegmentation(); fixture.detectChanges();
    http.expectOne('/api/v1/evaluations/evaluation-2').flush(second);
    await Promise.resolve();
    http.expectOne('/api/v1/images/image-2/content').flush(new Blob(['new image'], { type: 'image/png' }));
    await Promise.resolve(); fixture.detectChanges();
    const nextWorkspace = fixture.debugElement.query(By.directive(SegmentationWorkspaceComponent)).componentInstance as SegmentationWorkspaceComponent;
    expect(nextWorkspace).not.toBe(workspace);
    expect(nextWorkspace.box()).toBeNull();
    expect(nextWorkspace.result()).toBeNull();
    expect(nextWorkspace.quality()).toBeNull();
    component.enterClinicalAssessment({ reviewed_attempt_id: 'new-attempt', segmentation_quality: 'adequate' });
    fixture.detectChanges();
    http.expectOne('/api/v1/evaluations/evaluation-2').flush(second); fixture.detectChanges();
    const nextClinical = fixture.debugElement.query(By.directive(ClinicalAssessmentComponent)).componentInstance as ClinicalAssessmentComponent;
    expect(nextClinical).not.toBe(clinical);
    expect(nextClinical.form.getRawValue()).toEqual({ clinicalLs: null, confidencePercent: null });
    expect(nextClinical.review()).toBeNull();
    http.expectNone(() => true);
  });

  it('ignores new evaluation requests before clinical finalization', () => {
    loadRegions(); fillForm();
    const values = component.form.getRawValue();
    expect(element.textContent).not.toContain('New evaluation');
    component.startNewEvaluation();
    expect(component.form.getRawValue()).toEqual(values);
    component.evaluation.set(evaluation);
    component.phase.set('segmentation');
    component.startNewEvaluation();
    expect(component.phase()).toBe('segmentation');
    expect(component.evaluation()).toBe(evaluation);
    http.expectNone(() => true);
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
