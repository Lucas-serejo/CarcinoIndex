import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EvaluationResponse } from '../../api/api.models';
import { ClinicalAssessmentComponent } from './clinical-assessment.component';

describe('Clinical assessment', () => {
  let fixture: ComponentFixture<ClinicalAssessmentComponent>;
  let component: ClinicalAssessmentComponent;
  let http: HttpTestingController;
  let element: HTMLElement;
  const url = '/api/v1/evaluations/evaluation-1';
  const draft: EvaluationResponse = {
    evaluation_id: 'evaluation-1', image_id: 'image-1', pci_region_id: 6, annotator_code: 'MED01',
    status: 'draft', clinical_ls: null, annotator_confidence: null, created_at: '', finalized_at: null,
  };
  const finalized: EvaluationResponse = {
    ...draft, status: 'finalized', clinical_ls: 3, annotator_confidence: 0.82, finalized_at: '2026-09-26T12:00:00Z',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ClinicalAssessmentComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ClinicalAssessmentComponent);
    component = fixture.componentInstance;
    element = fixture.nativeElement as HTMLElement;
    fixture.componentRef.setInput('evaluationId', 'evaluation-1');
    fixture.detectChanges();
  });
  afterEach(() => { fixture.destroy(); http.verify(); });

  function load(record = draft): void {
    const request = http.expectOne(url);
    expect(request.request.method).toBe('GET');
    request.flush(record);
    fixture.detectChanges();
  }
  function button(label: string): HTMLButtonElement {
    return Array.from(element.querySelectorAll('button')).find(button => button.textContent?.trim() === label)!;
  }
  function review(confidence: number | null = 73): void {
    component.form.setValue({ clinicalLs: 2, confidencePercent: confidence });
    button('Review assessment').click();
    fixture.detectChanges();
  }
  function fail(requestUrl = `${url}/finalize`, status = 500): void {
    http.expectOne(requestUrl).flush({ error: { code: 'failed', message: 'Safe backend message.' } }, { status, statusText: 'Failure' });
    fixture.detectChanges();
  }

  it('retrieves persisted context and starts with exactly four unselected, labelled LS radios', () => {
    expect(element.textContent).toContain('Loading persisted evaluation');
    load();
    const radios = Array.from(element.querySelectorAll<HTMLInputElement>('fieldset input[type="radio"]'));
    expect(radios).toHaveLength(4);
    expect(radios.map(radio => radio.closest('label')?.textContent?.trim())).toEqual(['LS 0', 'LS 1', 'LS 2', 'LS 3']);
    expect(radios.every(radio => !radio.checked)).toBe(true);
    expect(component.form.getRawValue()).toEqual({ clinicalLs: null, confidencePercent: null });
    expect(element.querySelector('legend')?.textContent).toContain('Clinical LS');
    expect(element.textContent).toContain('does not infer LS');
    expect(element.textContent).toContain('not a SAM confidence score');
    expect(element.textContent).not.toMatch(/selected_score|lesion\s*size|\bcm\b|\bmm\b/i);
    expect(element.textContent).not.toContain('evaluation-1');
  });

  it('uses numeric native radio selections and associates required validation with the choices', () => {
    load();
    button('Review assessment').click();
    fixture.detectChanges();
    expect(component.state()).toBe('editing');
    expect(element.querySelector('fieldset')?.getAttribute('aria-invalid')).toBe('true');
    expect(element.querySelector('#ls-help')?.textContent).toContain('Select a clinical LS');
    element.querySelectorAll<HTMLInputElement>('input[type="radio"]')[0].click();
    expect(component.form.controls.clinicalLs.value).toBe(0);
    button('Review assessment').click();
    expect(component.review()?.clinical_ls).toBe(0);
    http.expectNone(`${url}/finalize`);
  });

  it.each([-1, 4, 1.5, NaN])('rejects invalid LS %s', value => {
    load();
    component.form.controls.clinicalLs.setValue(value);
    component.reviewAssessment();
    expect(component.state()).toBe('editing');
    http.expectNone(`${url}/finalize`);
  });

  it.each([-1, 101, NaN, Infinity])('rejects invalid confidence %s with associated error text', value => {
    load();
    review(value);
    expect(component.state()).toBe('editing');
    expect(element.querySelector('#confidence')?.getAttribute('aria-invalid')).toBe('true');
    expect(element.querySelector('#confidence-error')?.textContent).toContain('0 to 100');
    http.expectNone(`${url}/finalize`);
  });

  it.each([[null, null, 'Not provided'], [73, 0.73, '73%'], [0, 0, '0%'], [100, 1, '100%']] as const)(
    'reviews confidence %s and sends %s only after explicit finalization', (percent, backend, display) => {
      load();
      review(percent);
      http.expectNone(`${url}/finalize`);
      expect(element.textContent).toContain('LS 2');
      expect(element.textContent).toContain(display);
      expect(element.querySelector('input')).toBeNull();
      expect(element.textContent).toContain('irreversible');
      button('Finalize evaluation').click();
      const request = http.expectOne(`${url}/finalize`);
      expect(request.request.body).toEqual({ clinical_ls: 2, annotator_confidence: backend });
      request.flush({ ...finalized, clinical_ls: 2, annotator_confidence: backend });
    },
  );

  it('maps a cleared native confidence input to null', () => {
    load();
    const input = element.querySelector<HTMLInputElement>('#confidence')!;
    input.value = '73'; input.dispatchEvent(new Event('input'));
    expect(component.form.controls.confidencePercent.value).toBe(73);
    input.value = ''; input.dispatchEvent(new Event('input'));
    component.form.controls.clinicalLs.setValue(1);
    component.reviewAssessment();
    expect(component.review()?.annotator_confidence).toBeNull();
  });

  it('returns to editing without losing the entered values', () => {
    load(); review();
    button('Back to edit').click(); fixture.detectChanges();
    expect(component.form.getRawValue()).toEqual({ clinicalLs: 2, confidencePercent: 73 });
    expect(element.querySelector<HTMLInputElement>('#confidence')?.value).toBe('73');
    expect(element.querySelectorAll<HTMLInputElement>('input[type="radio"]')[2].checked).toBe(true);
    http.expectNone(`${url}/finalize`);
  });

  it('submits the captured snapshot once and blocks edit/refresh while finalizing', () => {
    load(); review();
    component.form.setValue({ clinicalLs: 0, confidencePercent: 0 });
    fixture.detectChanges();
    expect(element.textContent).toContain('73%');
    button('Finalize evaluation').click(); fixture.detectChanges();
    expect(button('Finalize evaluation').disabled).toBe(true);
    expect(button('Back to edit').disabled).toBe(true);
    expect(element.querySelector('[role="status"]')?.textContent).toContain('Finalizing');
    component.finalize(); component.backToEdit(); component.refreshEvaluation();
    expect(component.state()).toBe('finalizing');
    http.expectNone(url);
    const request = http.expectOne(`${url}/finalize`);
    expect(request.request.body).toEqual({ clinical_ls: 2, annotator_confidence: 0.73 });
    request.flush(finalized);
  });

  it('renders and emits the persisted final response, including values different from the review', () => {
    const emitted = vi.fn(); component.evaluationFinalized.subscribe(emitted);
    load(); review(); component.finalize();
    http.expectOne(`${url}/finalize`).flush(finalized); fixture.detectChanges();
    expect(emitted).toHaveBeenCalledExactlyOnceWith(finalized);
    expect(element.textContent).toContain('Clinical assessment finalized');
    expect(element.textContent).toContain('LS 3');
    expect(element.textContent).toContain('82%');
    expect(element.querySelector('input, button')).toBeNull();
    expect(element.textContent).toContain('clinical LS was supplied by the specialist');
    expect(element.textContent).toContain('does not accept, validate, or select a segmentation mask');
    expect(element.textContent).toContain('does not represent a complete 13-region PCI score');
    component.finalize(); http.expectNone(`${url}/finalize`);
  });

  it('immediately renders and emits an already finalized record without posting', () => {
    const emitted = vi.fn(); component.evaluationFinalized.subscribe(emitted);
    load({ ...finalized, annotator_confidence: null });
    expect(element.querySelector('input, button')).toBeNull();
    expect(element.textContent).toContain('Not provided');
    expect(emitted).toHaveBeenCalledExactlyOnceWith({ ...finalized, annotator_confidence: null });
    component.reviewAssessment(); component.finalize(); http.expectNone(`${url}/finalize`);
  });

  it('offers Retry after an initial retrieval failure', () => {
    fail(url, 404);
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('Safe backend message');
    expect(element.querySelector('input')).toBeNull();
    button('Retry').click(); load();
    expect(component.state()).toBe('editing');
  });

  it.each([409, 422, 500])('preserves the review after HTTP %s and allows an explicit retry', status => {
    load(); review(); const snapshot = component.review();
    component.finalize(); fail(`${url}/finalize`, status);
    expect(component.review()).toBe(snapshot);
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('Safe backend message');
    expect(button('Refresh evaluation state')).toBeDefined();
    button('Finalize evaluation').click();
    const request = http.expectOne(`${url}/finalize`);
    expect(request.request.body).toEqual(snapshot); request.flush(finalized);
  });

  it('recovers a lost finalization response by refreshing the persisted finalized record', () => {
    load(); review(); component.finalize();
    http.expectOne(`${url}/finalize`).error(new ProgressEvent('error')); fixture.detectChanges();
    const emitted = vi.fn(); component.evaluationFinalized.subscribe(emitted);
    button('Refresh evaluation state').click(); load(finalized);
    expect(component.state()).toBe('finalized');
    expect(emitted).toHaveBeenCalledExactlyOnceWith(finalized);
    expect(element.querySelector('input, button')).toBeNull();
    http.expectNone(`${url}/finalize`);
  });

  it('preserves the snapshot through a failed refresh and a subsequent draft response', () => {
    load(); review(); const snapshot = component.review();
    component.finalize(); fail(); button('Refresh evaluation state').click(); fail(url);
    expect(element.textContent).toContain('Evaluation retrieval failed');
    expect(component.review()).toBe(snapshot);
    button('Refresh evaluation state').click(); load();
    expect(component.state()).toBe('reviewing');
    expect(component.review()).toBe(snapshot);
    expect(element.textContent).toContain('73%');
    button('Finalize evaluation').click();
    const request = http.expectOne(`${url}/finalize`);
    expect(request.request.body).toEqual(snapshot); request.flush(finalized);
  });

  it('cancels initial retrieval on destruction', () => {
    const request = http.expectOne(url); fixture.destroy(); expect(request.cancelled).toBe(true);
  });
  it('cancels pending finalization on destruction without emitting', () => {
    load(); review(); const emitted = vi.fn(); component.evaluationFinalized.subscribe(emitted);
    component.finalize(); const request = http.expectOne(`${url}/finalize`);
    fixture.destroy(); expect(request.cancelled).toBe(true); expect(emitted).not.toHaveBeenCalled();
  });
  it('cancels recovery retrieval on destruction', () => {
    load(); review(); component.finalize(); fail(); component.refreshEvaluation();
    const request = http.expectOne(url); fixture.destroy(); expect(request.cancelled).toBe(true);
  });
});
