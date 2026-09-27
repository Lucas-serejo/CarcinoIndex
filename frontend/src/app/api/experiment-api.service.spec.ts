import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { ExperimentApiService } from './experiment-api.service';
import { HealthResponse } from './api.models';

describe('ExperimentApiService', () => {
  let service: ExperimentApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ExperimentApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  it.each([0.73, null])('finalizes with only the JSON clinical contract (confidence %s) and no timeout', async confidence => {
    vi.useFakeTimers();
    const body = { clinical_ls: 2, annotator_confidence: confidence };
    const result = firstValueFrom(service.finalizeEvaluation('evaluation-1', body));
    const request = http.expectOne('/api/v1/evaluations/evaluation-1/finalize');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).not.toBeInstanceOf(FormData);
    expect(request.request.body).toEqual(body);
    expect(Object.keys(request.request.body as object)).toEqual(['clinical_ls', 'annotator_confidence']);
    await vi.advanceTimersByTimeAsync(120000);
    expect(request.cancelled).toBe(false);
    request.flush({ evaluation_id: 'evaluation-1', status: 'finalized', ...body });
    expect((await result).status).toBe('finalized');
  });

  it.each([404, 409, 422, 500])('maps safe finalization errors for HTTP %s', async status => {
    const result = firstValueFrom(service.finalizeEvaluation('evaluation-1', { clinical_ls: 2, annotator_confidence: null }));
    const assertion = expect(result).rejects.toThrow('Safe finalization message.');
    http.expectOne('/api/v1/evaluations/evaluation-1/finalize').flush(
      { error: { code: 'failed', message: 'Safe finalization message.' } }, { status, statusText: 'Failure' },
    );
    await assertion;
  });

  it('retrieves a persisted evaluation', async () => {
    const result = firstValueFrom(service.getEvaluation('evaluation-1'));
    const request = http.expectOne('/api/v1/evaluations/evaluation-1');
    expect(request.request.method).toBe('GET');
    request.flush({ evaluation_id: 'evaluation-1' });
    expect((await result).evaluation_id).toBe('evaluation-1');
  });

  it.each(['image/png', 'image/jpeg'])('retrieves the original %s Blob', async (type) => {
    const blob = new Blob(['bytes'], { type });
    const result = firstValueFrom(service.getImageContent('image-1'));
    const request = http.expectOne('/api/v1/images/image-1/content');
    expect(request.request.method).toBe('GET');
    expect(request.request.responseType).toBe('blob');
    request.flush(blob);
    expect(await result).toBe(blob);
  });

  it('rejects unsupported image content', async () => {
    const result = firstValueFrom(service.getImageContent('image-1'));
    const assertion = expect(result).rejects.toThrow('not a supported JPEG or PNG');
    http.expectOne('/api/v1/images/image-1/content').flush(new Blob(['text'], { type: 'text/plain' }));
    await assertion;
  });

  it.each([
    [JSON.stringify({ error: { code: 'missing', message: 'Image content is unavailable.' } }), 'Image content is unavailable.'],
    ['private binary contents', 'Unable to reach the backend'],
    [JSON.stringify({ detail: 'private exception' }), 'Unable to reach the backend'],
  ])('maps binary error bodies safely', async (body, message) => {
    const result = firstValueFrom(service.getImageContent('image-1'));
    const assertion = expect(result).rejects.toThrow(message);
    http.expectOne('/api/v1/images/image-1/content').flush(new Blob([body], { type: 'application/json' }),
      { status: 404, statusText: 'Not Found' });
    await assertion;
  });

  it('posts exactly the persisted BOX contract without a multipart header or inference timeout', async () => {
    vi.useFakeTimers();
    const result = firstValueFrom(service.createBoxSegmentationAttempt('evaluation-1', { xMin: 20, yMin: 30, xMax: 200, yMax: 300 }));
    const request = http.expectOne('/api/v1/evaluations/evaluation-1/segmentations');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toBeInstanceOf(FormData);
    const body = request.request.body as FormData;
    expect([...body.keys()]).toEqual(['prompt_type', 'box', 'multimask_output']);
    expect(body.get('prompt_type')).toBe('box');
    expect(JSON.parse(body.get('box') as string)).toEqual([20, 30, 200, 300]);
    expect(body.get('multimask_output')).toBe('true');
    expect(body.has('image')).toBe(false);
    expect(request.request.headers.has('Content-Type')).toBe(false);
    await vi.advanceTimersByTimeAsync(120000);
    expect(request.cancelled).toBe(false);
    request.flush({ sequence_number: 1 });
    expect((await result).sequence_number).toBe(1);
  });

  it('loads PCI regions from the relative backend endpoint', async () => {
    const result = firstValueFrom(service.getRegions());
    const request = http.expectOne('/api/v1/pci/regions');
    expect(request.request.method).toBe('GET');
    request.flush({ regions: [] });
    expect(await result).toEqual({ regions: [] });
  });

  it('posts only the case contract', async () => {
    const body = { anonymous_patient_code: 'PATIENT-001' };
    const result = firstValueFrom(service.createCase(body));
    const request = http.expectOne('/api/v1/cases');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ case_id: 'case-1', ...body, created_at: '2026-09-25T12:00:00Z' });
    expect((await result).case_id).toBe('case-1');
  });

  it('uploads the exact selected File without forcing a multipart header', async () => {
    const file = new File(['image'], 'private-name.png', { type: 'image/png' });
    const result = firstValueFrom(service.uploadCaseImage('case-1', file));
    const request = http.expectOne('/api/v1/cases/case-1/images');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toBeInstanceOf(FormData);
    const body = request.request.body as FormData;
    expect([...body.keys()]).toEqual(['image']);
    expect(body.get('image')).toBe(file);
    expect(request.request.headers.has('Content-Type')).toBe(false);
    request.flush({ image_id: 'image-1' });
    expect((await result).image_id).toBe('image-1');
  });

  it('posts only region and annotator for a draft evaluation', async () => {
    const body = { pci_region_id: 0, annotator_code: 'MED01' };
    const result = firstValueFrom(service.createEvaluation('image-1', body));
    const request = http.expectOne('/api/v1/images/image-1/evaluations');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(body);
    request.flush({ evaluation_id: 'evaluation-1', ...body });
    expect((await result).evaluation_id).toBe('evaluation-1');
  });

  it('uses safe envelope mapping for lifecycle errors too', async () => {
    const result = firstValueFrom(service.createCase({ anonymous_patient_code: 'P01' }));
    const assertion = expect(result).rejects.toThrow('Could not create the clinical case.');
    http.expectOne('/api/v1/cases').flush(
      { error: { code: 'case_creation_failed', message: 'Could not create the clinical case.' } },
      { status: 500, statusText: 'Server Error' },
    );
    await assertion;
  });

  it('requests the relative health endpoint and preserves the backend response', async () => {
    const response: HealthResponse = {
      status: 'ok',
      model: {
        loaded: true,
        name: 'sam2.1_hiera_small',
        device: 'cpu',
        dtype: 'torch.float32',
      },
    };
    const result = firstValueFrom(service.getHealth());
    const request = http.expectOne('/health');
    expect(request.request.method).toBe('GET');
    request.flush(response);
    expect(await result).toEqual(response);
  });

  it('extracts a message from the documented backend error envelope', async () => {
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Segmentation service unavailable.',
    );
    http
      .expectOne('/health')
      .flush(
        {
          error: {
            code: 'service_unavailable',
            message: 'Segmentation service unavailable.',
          },
        },
        { status: 503, statusText: 'Unavailable' },
      );
    await assertion;
  });

  it.each([null, '<html>Bad gateway</html>', { error: { message: 42 } }])(
    'uses a fallback for unexpected error bodies: %j',
    async (body) => {
      const result = firstValueFrom(service.getHealth());
      const assertion = expect(result).rejects.toThrow(
        'Unable to reach the backend',
      );
      http
        .expectOne('/health')
        .flush(body, { status: 502, statusText: 'Bad Gateway' });
      await assertion;
    },
  );

  it('stops a stalled health request after ten seconds', async () => {
    vi.useFakeTimers();
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Unable to reach the backend',
    );
    const request = http.expectOne('/health');
    await vi.advanceTimersByTimeAsync(10000);
    await assertion;
    expect(request.cancelled).toBe(true);
  });
});
